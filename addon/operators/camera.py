import bpy
import os
from mathutils import Vector, Matrix
from ..utils.ray_casting import is_camera_inside_mesh


class CAMERA_OT_generate_from_faces(bpy.types.Operator):
    """Generate camera keyframes from helper mesh faces"""

    bl_idname = "camera.generate_from_faces"
    bl_label = "Generate Camera Keyframes"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return len(context.scene.helper_meshes) > 0

    def execute(self, context):
        scene = context.scene

        # Get or create camera
        camera = scene.camera
        if not camera:
            bpy.ops.object.camera_add()
            camera = context.active_object
            scene.camera = camera

        # Set camera properties
        camera.data.lens = scene.camera_focal_length

        # Clear existing keyframes
        if camera.animation_data:
            camera.animation_data_clear()

        frame_num = 1
        total_faces = 0
        rejected_cameras = 0

        # Get helper mesh objects to exclude from interior detection
        helper_objects = set()
        for item in scene.helper_meshes:
            try:
                if item.mesh_object and item.mesh_object.type == "MESH":
                    helper_objects.add(item.mesh_object)
            except (AttributeError, ReferenceError):
                pass

        # Process each helper mesh
        for helper_item in scene.helper_meshes:
            mesh_obj = helper_item.mesh_object
            if not mesh_obj or mesh_obj.type != "MESH":
                continue

            # Get evaluated mesh (with modifiers applied)
            depsgraph = context.evaluated_depsgraph_get()
            mesh_eval = mesh_obj.evaluated_get(depsgraph)
            mesh = mesh_eval.to_mesh()

            # Get world matrix
            world_matrix = mesh_obj.matrix_world

            # Process each face
            for poly in mesh.polygons:
                # Calculate face center in local space
                face_center = Vector((0, 0, 0))
                for vert_idx in poly.vertices:
                    face_center += mesh.vertices[vert_idx].co
                face_center /= len(poly.vertices)

                # Transform to world space
                face_center = world_matrix @ face_center

                # Get face normal in world space
                face_normal = world_matrix.to_3x3() @ poly.normal
                face_normal.normalize()

                # Camera looks opposite to face normal
                look_dir = -face_normal

                # Calculate up vector
                world_up = Vector((0, 0, 1))
                right = look_dir.cross(world_up)

                # Handle case where look direction is parallel to world up
                if right.length < 0.001:
                    world_up = Vector((0, 1, 0))
                    right = look_dir.cross(world_up)

                right.normalize()
                up = right.cross(look_dir)
                up.normalize()

                # Create rotation matrix
                rot_matrix = Matrix((right, up, -look_dir)).transposed()

                # Check if camera is inside a mesh (if enabled)
                if scene.skip_interior_cameras:
                    # Offset the ray origin slightly along the face normal to avoid self-intersection
                    offset_distance = 0.001  # Small offset to avoid hitting the face we're on
                    offset_origin = face_center + (face_normal * offset_distance)

                    # Cast ray in viewing direction (opposite to face normal)
                    if is_camera_inside_mesh(context, offset_origin, look_dir, helper_objects):
                        rejected_cameras += 1
                        continue  # Skip this camera position

                    # Check if any object is too close (within near clipping plane)
                    near_clip = camera.data.clip_start
                    depsgraph = context.evaluated_depsgraph_get()
                    # Cast ray from camera position in viewing direction
                    result, location, normal, index, object, matrix = scene.ray_cast(
                        depsgraph, face_center, look_dir
                    )
                    if result:
                        # Calculate distance to hit point
                        distance = (location - face_center).length
                        if distance < near_clip:
                            rejected_cameras += 1
                            continue  # Skip this camera position

                # Set camera location and rotation
                camera.location = face_center
                camera.rotation_euler = rot_matrix.to_euler()

                # Insert keyframes
                camera.keyframe_insert(data_path="location", frame=frame_num)
                camera.keyframe_insert(data_path="rotation_euler", frame=frame_num)

                frame_num += 1
                total_faces += 1

            # Clean up evaluated mesh
            mesh_eval.to_mesh_clear()

        # Set frame range
        scene.frame_start = 1
        scene.frame_end = max(1, frame_num - 1)

        # Update render settings
        scene.render.resolution_x = scene.output_width
        scene.render.resolution_y = scene.output_height
        output_dir = bpy.path.abspath(scene.output_folder)
        scene.render.filepath = os.path.join(output_dir, "images", "")

        # Report results
        if scene.skip_interior_cameras and rejected_cameras > 0:
            self.report(
                {"INFO"},
                f"Generated {total_faces} camera keyframes from {len(scene.helper_meshes)} helper mesh(es). Rejected {rejected_cameras} interior cameras.",
            )
        else:
            self.report(
                {"INFO"},
                f"Generated {total_faces} camera keyframes from {len(scene.helper_meshes)} helper mesh(es)",
            )

        return {"FINISHED"}


class RENDER_OT_animation_to_export(bpy.types.Operator):
    """Render animation to the export output folder"""

    bl_idname = "render.animation_to_export"
    bl_label = "Render Animation"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return (
            context.scene.camera
            and context.scene.frame_end >= context.scene.frame_start
        )

    def execute(self, context):
        scene = context.scene

        # Set render output to images subfolder
        output_dir = bpy.path.abspath(scene.output_folder)
        images_dir = os.path.join(output_dir, "images")
        if not os.path.exists(images_dir):
            os.makedirs(images_dir)

        scene.render.filepath = os.path.join(images_dir, "")

        # INVOKE_DEFAULT opens the render window with progress, like Render > Render Animation
        bpy.ops.render.render('INVOKE_DEFAULT', animation=True)

        return {"FINISHED"}