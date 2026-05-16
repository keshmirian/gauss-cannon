import bpy
import os
import time
import numpy as np
import gpu
from ..utils.ray_casting import (
    build_scene_bvh,
    cast_ray_through_pixel,
    cast_scene_rays,
    precompute_camera_rays,
)
from ..utils.coordinate_systems import write_ply_bulk


class EXPORT_OT_pointcloud_ply(bpy.types.Operator):
    """Generate colored point cloud in PLY format from selected objects"""

    bl_idname = "export.pointcloud_ply"
    bl_label = "Generate Point Cloud PLY from Selected"
    bl_options = {"REGISTER"}

    # Modal state
    _timer = None
    _frame_idx = 0
    _frame_start = 0
    _frame_end = 0
    _total_frames = 0
    _selected_meshes = []
    _scene_bvh = None
    _cam_dirs = None
    _cam_offsets = None
    _cam_type = "PERSP"
    _near_clip = 0.0
    _points_buf = None
    _colors_buf = None
    _point_count = 0
    _use_gpu = False
    _resolution = 8
    _orig_persistent_data = False
    _orig_frame = 0
    _stride = 1
    _is_running = False
    _start_time = 0

    @classmethod
    def poll(cls, context):
        return (
            context.selected_objects
            and any(obj.type == "MESH" for obj in context.selected_objects)
            and context.scene.camera
            and context.scene.frame_end >= context.scene.frame_start
            and context.scene.output_folder.strip()
            and not cls._is_running
        )

    def check_gpu_available(self):
        """Check if GPU acceleration is available."""
        try:
            test_data = np.array([1.0, 2.0, 3.0], dtype=np.float32)
            buffer = gpu.types.Buffer("FLOAT", 3, test_data)
            del buffer
            return True
        except Exception:
            return False

    def render_frame_to_pixels(self, context, resolution):
        """Render current frame and return pixel data"""
        scene = context.scene

        # Store original settings
        orig_res_x = scene.render.resolution_x
        orig_res_y = scene.render.resolution_y
        orig_percentage = scene.render.resolution_percentage
        orig_filepath = scene.render.filepath
        orig_file_format = scene.render.image_settings.file_format
        orig_color_mode = scene.render.image_settings.color_mode

        # Temporarily hide helper meshes from viewport
        helper_meshes = []
        for item in scene.helper_meshes:
            try:
                if item.mesh_object:
                    helper_meshes.append((item.mesh_object, item.mesh_object.hide_viewport))
            except (AttributeError, ReferenceError):
                pass
        for obj, _ in helper_meshes:
            obj.hide_viewport = True

        # Set low resolution and force PNG output
        scene.render.resolution_x = resolution
        scene.render.resolution_y = resolution
        scene.render.resolution_percentage = 100
        scene.render.image_settings.file_format = 'PNG'
        scene.render.image_settings.color_mode = 'RGBA'

        # Render to temporary image
        temp_path = os.path.join(
            bpy.app.tempdir, f"pointcloud_temp_{scene.frame_current}.png"
        )
        scene.render.filepath = temp_path

        try:
            # Render frame
            bpy.ops.render.render(write_still=True)

            # Load rendered image
            img = bpy.data.images.load(temp_path)

            # Get pixel data as numpy array
            pixels = np.array(img.pixels[:])
            pixels = pixels.reshape((resolution, resolution, 4))

            # Clean up
            bpy.data.images.remove(img)
            if os.path.exists(temp_path):
                os.remove(temp_path)

            return pixels

        finally:
            # Restore settings
            scene.render.resolution_x = orig_res_x
            scene.render.resolution_y = orig_res_y
            scene.render.resolution_percentage = orig_percentage
            scene.render.filepath = orig_filepath
            scene.render.image_settings.file_format = orig_file_format
            scene.render.image_settings.color_mode = orig_color_mode

            # Restore helper mesh visibility
            for obj, orig_hide in helper_meshes:
                obj.hide_viewport = orig_hide

    def execute(self, context):
        scene = context.scene
        self._resolution = scene.pointcloud_resolution

        # Get selected mesh objects, excluding helper meshes
        helper_mesh_objects = set()
        for item in scene.helper_meshes:
            try:
                if item.mesh_object:
                    helper_mesh_objects.add(item.mesh_object)
            except (AttributeError, ReferenceError):
                pass

        self._selected_meshes = [
            obj
            for obj in context.selected_objects
            if obj.type == "MESH" and obj not in helper_mesh_objects
        ]

        if not self._selected_meshes:
            self.report(
                {"ERROR"}, "No mesh objects selected (helper meshes are excluded)"
            )
            return {"CANCELLED"}

        # Initialize state
        self._frame_start = scene.frame_start
        self._frame_end = scene.frame_end
        self._frame_idx = self._frame_start
        self._stride = scene.pointcloud_stride
        self._total_frames = len(range(self._frame_start, self._frame_end + 1, self._stride))
        self._use_gpu = scene.use_gpu_acceleration and self.check_gpu_available()
        self._orig_frame = scene.frame_current

        # Hoist camera attrs that don't change between frames out of the
        # per-pixel hot path.
        cam_data = scene.camera.data
        self._cam_type = cam_data.type
        self._near_clip = cam_data.clip_start

        # Static-scene precomputes: a single world-space BVH spanning every
        # selected mesh, and per-pixel cam-space ray data. Both depend only
        # on geometry + camera intrinsics + resolution, none of which change
        # across the frame range, so they're built exactly once.
        if self._use_gpu:
            self._scene_bvh = build_scene_bvh(self._selected_meshes)
            self._cam_dirs, self._cam_offsets = precompute_camera_rays(
                cam_data, self._resolution
            )
        else:
            self._scene_bvh = None
            self._cam_dirs = None
            self._cam_offsets = None

        # Preallocate output buffers sized to the absolute upper bound
        # (every pixel of every frame hits geometry). _point_count tracks
        # the live size so finish() can slice down to actual hits.
        max_points = self._total_frames * self._resolution * self._resolution
        self._points_buf = np.empty((max_points, 3), dtype=np.float32)
        self._colors_buf = np.empty((max_points, 3), dtype=np.float32)
        self._point_count = 0

        # Store original persistent data setting
        self._orig_persistent_data = scene.render.use_persistent_data
        scene.render.use_persistent_data = True

        # Mark as running
        EXPORT_OT_pointcloud_ply._is_running = True
        self._start_time = time.time()

        if self._use_gpu:
            self.report({"INFO"}, "Starting point cloud generation (GPU accelerated)")
        else:
            self.report({"INFO"}, "Starting point cloud generation (CPU fallback)")

        # Start modal timer
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.1, window=context.window)
        wm.modal_handler_add(self)

        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type == "ESC":
            self.cancel(context)
            self.report({"WARNING"}, "Point cloud generation cancelled")
            return {"CANCELLED"}

        if event.type == "TIMER":
            scene = context.scene

            # Check if we're done
            if self._frame_idx > self._frame_end:
                return self.finish(context)

            # Update progress in header
            frames_done = (self._frame_idx - self._frame_start) // self._stride
            frames_remaining = self._total_frames - frames_done
            progress_pct = int((frames_done / self._total_frames) * 100)

            # Estimate time remaining
            elapsed = time.time() - self._start_time
            if frames_done > 0:
                time_per_frame = elapsed / frames_done
                remaining_secs = int(time_per_frame * frames_remaining)
                if remaining_secs >= 60:
                    time_str = f"{remaining_secs // 60}m {remaining_secs % 60}s"
                else:
                    time_str = f"{remaining_secs}s"
                time_info = f" - ~{time_str} remaining"
            else:
                time_info = ""

            context.area.header_text_set(
                f"Point Cloud: Frame {self._frame_idx}/{self._frame_end} ({progress_pct}%){time_info} - ESC to cancel"
            )

            # Process current frame
            scene.frame_set(self._frame_idx)
            pixels = self.render_frame_to_pixels(context, self._resolution)

            if self._use_gpu:
                written = cast_scene_rays(
                    self._scene_bvh,
                    scene.camera.matrix_world,
                    pixels,
                    self._cam_dirs,
                    self._cam_offsets,
                    self._resolution,
                    self._near_clip,
                    self._cam_type,
                    self._points_buf,
                    self._colors_buf,
                    self._point_count,
                )
                self._point_count += written
            else:
                # CPU fallback: legacy per-mesh path. Still benefits from the
                # alpha skip and preallocated buffers, but ray casting goes
                # through Blender's per-mesh BVH cache rather than our merged
                # scene BVH.
                R = self._resolution
                # Blender stores image pixels bottom-up, so flip rows once
                # to align with the (y, x) ordering cast_ray_through_pixel
                # expects (y=0 is the top of the camera frustum).
                pixels_flipped = pixels[::-1, :, :]
                hit_mask = pixels_flipped[:, :, 3] > 0.0
                for ray_idx in np.argwhere(hit_mask):
                    y_flat, x = int(ray_idx[0]), int(ray_idx[1])
                    hit_point = cast_ray_through_pixel(
                        scene,
                        scene.camera,
                        x + 0.5,
                        y_flat + 0.5,
                        R,
                        R,
                        self._selected_meshes,
                    )
                    if hit_point:
                        slot = self._point_count
                        self._points_buf[slot, 0] = hit_point.x
                        self._points_buf[slot, 1] = hit_point.y
                        self._points_buf[slot, 2] = hit_point.z
                        self._colors_buf[slot] = pixels_flipped[y_flat, x, :3]
                        self._point_count += 1

            self._frame_idx += self._stride

        return {"RUNNING_MODAL"}

    def _release_state(self):
        """Drop references to large per-run state so memory isn't pinned
        after the operator exits."""
        self._scene_bvh = None
        self._cam_dirs = None
        self._cam_offsets = None
        self._points_buf = None
        self._colors_buf = None

    def finish(self, context):
        """Complete the operation and write output file"""
        scene = context.scene

        # Clean up timer
        if self._timer:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None

        # Restore state
        scene.render.use_persistent_data = self._orig_persistent_data
        scene.frame_set(self._orig_frame)
        context.area.header_text_set(None)
        EXPORT_OT_pointcloud_ply._is_running = False

        # Write PLY file
        output_dir = bpy.path.abspath(scene.output_folder)
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        output_path = os.path.join(output_dir, "pointcloud.ply")

        coordinate_system = "Z_UP" if scene.export_mode == "BRUSH" else scene.coordinate_system
        points = self._points_buf[: self._point_count]
        colors = self._colors_buf[: self._point_count]
        write_ply_bulk(output_path, points, colors, coordinate_system)

        coord_info = "Y-up" if coordinate_system == "Y_UP" else "Z-up"
        self.report(
            {"INFO"},
            f"Generated {self._point_count} points from {self._total_frames} frames ({coord_info})",
        )

        self._release_state()
        return {"FINISHED"}

    def cancel(self, context):
        """Handle cancellation"""
        scene = context.scene

        # Clean up timer
        if self._timer:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None

        # Restore state
        scene.render.use_persistent_data = self._orig_persistent_data
        scene.frame_set(self._orig_frame)
        context.area.header_text_set(None)
        EXPORT_OT_pointcloud_ply._is_running = False
        self._release_state()
