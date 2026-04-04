import bpy
import os
import time
import numpy as np
import gpu
from ..utils.ray_casting import cast_ray_through_pixel, gpu_accelerated_ray_cast
from ..utils.coordinate_systems import write_ply_header, write_ply_point


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
    _all_points = []
    _all_colors = []
    _selected_meshes = []
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

        # Set low resolution
        scene.render.resolution_x = resolution
        scene.render.resolution_y = resolution
        scene.render.resolution_percentage = 100

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

            # Restore helper mesh visibility
            for obj, orig_hide in helper_meshes:
                obj.hide_viewport = orig_hide

    def write_ply(self, filepath, points, colors, coordinate_system):
        """Write point cloud to PLY file"""
        num_points = len(points)

        with open(filepath, "wb") as f:
            # Write PLY header
            header = write_ply_header(num_points)
            f.write(header.encode("ascii"))

            # Write binary data
            for i in range(num_points):
                point_data = write_ply_point(points[i], colors[i], coordinate_system)
                f.write(point_data)

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
        self._all_points = []
        self._all_colors = []
        self._use_gpu = scene.use_gpu_acceleration and self.check_gpu_available()
        self._orig_frame = scene.frame_current

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
                frame_results = gpu_accelerated_ray_cast(
                    scene, scene.camera, self._resolution, self._selected_meshes, pixels
                )
                for hit_point, color in frame_results:
                    self._all_points.append(hit_point)
                    self._all_colors.append(color)
            else:
                for y in range(self._resolution):
                    for x in range(self._resolution):
                        color = pixels[self._resolution - 1 - y, x, :3]
                        hit_point = cast_ray_through_pixel(
                            scene,
                            scene.camera,
                            x + 0.5,
                            y + 0.5,
                            self._resolution,
                            self._resolution,
                            self._selected_meshes,
                        )
                        if hit_point:
                            self._all_points.append(hit_point)
                            self._all_colors.append(color)

            self._frame_idx += self._stride

        return {"RUNNING_MODAL"}

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

        self.write_ply(output_path, self._all_points, self._all_colors, scene.coordinate_system)

        coord_info = "Y-up" if scene.coordinate_system == "Y_UP" else "Z-up"
        self.report(
            {"INFO"},
            f"Generated {len(self._all_points)} points from {self._total_frames} frames ({coord_info})",
        )

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
