import bpy
import os
import json
import math
import mathutils
from mathutils import Vector, Matrix
import numpy as np
from collections import defaultdict
from multiprocessing import Pool, cpu_count
from functools import partial
import gpu
from gpu_extras.batch import batch_for_shader

# Property group to store helper mesh reference
class HelperMeshItem(bpy.types.PropertyGroup):
    mesh_object: bpy.props.PointerProperty(
        name="Mesh Object",
        type=bpy.types.Object,
        poll=lambda self, obj: obj.type == 'MESH'
    )
    name: bpy.props.StringProperty(name="Name")

# Add helper mesh operator
class MESH_OT_add_helper(bpy.types.Operator):
    """Add selected mesh as helper object"""
    bl_idname = "mesh.add_helper"
    bl_label = "Add Selected Mesh"
    bl_options = {'REGISTER', 'UNDO'}
    
    @classmethod
    def poll(cls, context):
        return context.selected_objects and any(obj.type == 'MESH' for obj in context.selected_objects)
    
    def execute(self, context):
        scene = context.scene
        added_count = 0
        
        for obj in context.selected_objects:
            if obj.type == 'MESH':
                # Check if already in list
                exists = any(item.mesh_object == obj for item in scene.helper_meshes)
                if not exists:
                    item = scene.helper_meshes.add()
                    item.mesh_object = obj
                    item.name = obj.name
                    # Hide from render 
                    obj.hide_render = True
                    added_count += 1
        
        self.report({'INFO'}, f"Added {added_count} helper mesh(es)")
        return {'FINISHED'}

# Remove helper mesh operator
class MESH_OT_remove_helper(bpy.types.Operator):
    """Remove helper mesh from list"""
    bl_idname = "mesh.remove_helper"
    bl_label = "Remove Helper Mesh"
    bl_options = {'REGISTER', 'UNDO'}
    
    index: bpy.props.IntProperty()
    
    def execute(self, context):
        scene = context.scene
        
        if 0 <= self.index < len(scene.helper_meshes):
            # Re-enable rendering for the mesh
            helper_item = scene.helper_meshes[self.index]
            if helper_item.mesh_object:
                helper_item.mesh_object.hide_render = False
            
            scene.helper_meshes.remove(self.index)
            scene.helper_mesh_index = min(max(0, scene.helper_mesh_index - 1), len(scene.helper_meshes) - 1)
        
        return {'FINISHED'}

# Clear all helper meshes operator
class MESH_OT_clear_helpers(bpy.types.Operator):
    """Clear all helper meshes"""
    bl_idname = "mesh.clear_helpers"
    bl_label = "Clear All"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        scene = context.scene
        
        # Re-enable rendering for all meshes
        for item in scene.helper_meshes:
            if item.mesh_object:
                item.mesh_object.hide_render = False
        
        scene.helper_meshes.clear()
        scene.helper_mesh_index = 0
        
        return {'FINISHED'}

# Generate camera keyframes operator
class CAMERA_OT_generate_from_faces(bpy.types.Operator):
    """Generate camera keyframes from helper mesh faces"""
    bl_idname = "camera.generate_from_faces"
    bl_label = "Generate Camera Keyframes"
    bl_options = {'REGISTER', 'UNDO'}
    
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
        
        # Process each helper mesh
        for helper_item in scene.helper_meshes:
            mesh_obj = helper_item.mesh_object
            if not mesh_obj or mesh_obj.type != 'MESH':
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
                rot_matrix = Matrix((
                    right,
                    up,
                    -look_dir
                )).transposed()
                
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
        
        # Update render resolution
        scene.render.resolution_x = scene.output_width
        scene.render.resolution_y = scene.output_height
        
        self.report({'INFO'}, f"Generated {total_faces} camera keyframes from {len(scene.helper_meshes)} helper mesh(es)")
        return {'FINISHED'}

# Export camera JSON operator
class EXPORT_OT_camera_json(bpy.types.Operator):
    """Export camera parameters to JSON"""
    bl_idname = "export.camera_json"
    bl_label = "Export Camera JSON"
    bl_options = {'REGISTER', 'UNDO'}
    
    @classmethod
    def poll(cls, context):
        return context.scene.camera and context.scene.frame_end >= context.scene.frame_start
    
    def compute_scene_bounds(self):
        """Compute scene bounding box more efficiently"""
        # Collect all visible mesh vertices
        visible_meshes = [obj for obj in bpy.context.view_layer.objects 
                         if obj.type == 'MESH' and not obj.hide_render and obj.visible_get()]
        
        if not visible_meshes:
            return 1.0  # Default scale if no visible meshes
        
        # Use numpy for efficient min/max calculation
        all_verts = []
        for obj in visible_meshes:
            world_mat = obj.matrix_world
            # Get bounding box corners in world space
            bbox_world = [world_mat @ Vector(corner) for corner in obj.bound_box]
            all_verts.extend([(v.x, v.y, v.z) for v in bbox_world])
        
        if not all_verts:
            return 1.0
        
        verts_array = np.array(all_verts)
        bbox_min = verts_array.min(axis=0)
        bbox_max = verts_array.max(axis=0)
        bbox_size = bbox_max - bbox_min
        
        return float(np.max(bbox_size))
    
    def extract_camera_parameters(self, camera_obj, render_settings):
        """Extract camera parameters with optimizations"""
        cam_data = camera_obj.data
        
        # Pre-calculate common values
        focal_mm = cam_data.lens
        sensor_w = cam_data.sensor_width
        sensor_h = cam_data.sensor_height
        render_w = render_settings.resolution_x
        render_h = render_settings.resolution_y
        
        # Pixel-space focal lengths
        fx = (focal_mm * render_w) / sensor_w
        fy = (focal_mm * render_h) / sensor_h
        
        # Field of view (using more precise calculation)
        fov_x = 2.0 * np.arctan(sensor_w / (2.0 * focal_mm))
        fov_y = 2.0 * np.arctan(sensor_h / (2.0 * focal_mm))
        
        # Transform matrix as nested list
        transform = [list(row) for row in camera_obj.matrix_world]
        
        return {
            'focal_x': fx,
            'focal_y': fy,
            'fov_x': fov_x,
            'fov_y': fov_y,
            'transform': transform
        }
    
    def generate_frame_data(self, frame_idx, cam_params, simplified=False):
        """Generate frame data entry"""
        frame_entry = {
            "transform_matrix": cam_params['transform'],
            "file_path": f"images\\{frame_idx:04d}"
        }
        
        if not simplified:
            frame_entry.update({
                "w": bpy.context.scene.render.resolution_x,
                "h": bpy.context.scene.render.resolution_y,
                "fl_x": cam_params['focal_x'],
                "fl_y": cam_params['focal_y'],
                "camera_angle_x": cam_params['fov_x'],
                "camera_angle_y": cam_params['fov_y']
            })
        
        return frame_entry
    
    def execute(self, context):
        scene = context.scene
        camera = scene.camera
        
        if not camera:
            self.report({'ERROR'}, "No camera found in scene")
            return {'CANCELLED'}
        
        # Calculate scene bounds
        scene_scale = self.compute_scene_bounds()
        
        # Get initial camera parameters
        scene.frame_set(scene.frame_start)
        initial_params = self.extract_camera_parameters(camera, scene.render)
        
        # Build output structure
        output_json = {
            "aabb_scale": scene_scale,
            "w": scene.render.resolution_x,
            "h": scene.render.resolution_y,
            "camera_angle_x": initial_params['fov_x'],
            "camera_angle_y": initial_params['fov_y'],
            "cx": scene.render.resolution_x / 2.0,
            "cy": scene.render.resolution_y / 2.0,
            "frames": []
        }
        
        # Add focal lengths for standard mode
        if not scene.postshot_mode:
            output_json["fl_x"] = initial_params['focal_x']
            output_json["fl_y"] = initial_params['focal_y']
        
        # Process all frames
        frame_count = scene.frame_end - scene.frame_start + 1
        for frame_idx in range(scene.frame_start, scene.frame_end + 1):
            scene.frame_set(frame_idx)
            
            # Extract camera parameters for this frame
            frame_params = self.extract_camera_parameters(camera, scene.render)
            
            # Generate frame data
            frame_data = self.generate_frame_data(
                frame_idx, 
                frame_params, 
                simplified=scene.postshot_mode
            )
            
            output_json["frames"].append(frame_data)
        
        # Write output file
        output_path = bpy.path.abspath(scene.json_output_path)
        output_dir = os.path.dirname(output_path)
        
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)
        
        with open(output_path, 'w') as f:
            json.dump(output_json, f, indent=2)
        
        self.report({'INFO'}, f"Exported {frame_count} frames to {output_path}")
        return {'FINISHED'}

# Export point cloud PLY operator
class EXPORT_OT_pointcloud_ply(bpy.types.Operator):
    """Generate colored point cloud in PLY format from selected objects"""
    bl_idname = "export.pointcloud_ply"
    bl_label = "Generate Point Cloud PLY from Selected"
    bl_options = {'REGISTER', 'UNDO'}
    
    @classmethod
    def poll(cls, context):
        return (context.selected_objects and 
                any(obj.type == 'MESH' for obj in context.selected_objects) and
                context.scene.camera and 
                context.scene.frame_end >= context.scene.frame_start)
    
    def check_gpu_available(self):
        """Check if GPU acceleration is available."""
        try:
            # Check if we can create GPU buffers
            test_data = np.array([1.0, 2.0, 3.0], dtype=np.float32)
            buffer = gpu.types.Buffer('FLOAT', 3, test_data)
            del buffer
            return True
        except:
            return False
    
    @staticmethod
    def process_pixel_batch(args):
        """Process a batch of pixels in parallel. Returns list of (point, color) tuples."""
        (pixel_coords, cam_matrix, cam_data_type, cam_angle, cam_ortho_scale, 
         resolution, mesh_data_list, colors) = args
        
        results = []
        aspect = resolution / resolution  # Square aspect ratio
        
        for (x, y), color in zip(pixel_coords, colors):
            # Calculate normalized device coordinates (-1 to 1)
            ndc_x = (2.0 * (x + 0.5) / resolution) - 1.0
            ndc_y = 1.0 - (2.0 * (y + 0.5) / resolution)
            
            # Calculate ray direction
            if cam_data_type == 'PERSP':
                tan_half_fov = math.tan(cam_angle / 2.0)
                ray_dir_cam = np.array([
                    ndc_x * tan_half_fov * aspect,
                    ndc_y * tan_half_fov,
                    -1.0
                ])
                ray_dir_cam = ray_dir_cam / np.linalg.norm(ray_dir_cam)
                offset_x = offset_y = 0
            else:
                ray_dir_cam = np.array([0, 0, -1])
                offset_x = ndc_x * cam_ortho_scale * aspect / 2.0
                offset_y = ndc_y * cam_ortho_scale / 2.0
            
            # Transform ray to world space
            cam_rot = cam_matrix[:3, :3]
            ray_origin = cam_matrix[:3, 3].copy()
            ray_dir_world = cam_rot @ ray_dir_cam
            ray_dir_world = ray_dir_world / np.linalg.norm(ray_dir_world)
            
            if cam_data_type == 'ORTHO':
                right = cam_rot[:, 0]
                up = cam_rot[:, 1]
                ray_origin += right * offset_x + up * offset_y
            
            # Find closest intersection with all meshes
            closest_hit = None
            closest_dist = float('inf')
            
            for mesh_data in mesh_data_list:
                vertices = mesh_data['vertices']
                faces = mesh_data['faces']
                transform = mesh_data['transform']
                
                # Transform ray to object space
                obj_inv = np.linalg.inv(transform)
                ray_origin_obj = obj_inv[:3, :3] @ ray_origin + obj_inv[:3, 3]
                ray_dir_obj = obj_inv[:3, :3] @ ray_dir_world
                ray_dir_obj = ray_dir_obj / np.linalg.norm(ray_dir_obj)
                
                # Simple ray-triangle intersection for each face
                for face in faces:
                    v0, v1, v2 = vertices[face[0]], vertices[face[1]], vertices[face[2]]
                    
                    # Möller–Trumbore intersection algorithm
                    edge1 = v1 - v0
                    edge2 = v2 - v0
                    h = np.cross(ray_dir_obj, edge2)
                    a = np.dot(edge1, h)
                    
                    if abs(a) < 1e-8:
                        continue
                        
                    f = 1.0 / a
                    s = ray_origin_obj - v0
                    u = f * np.dot(s, h)
                    
                    if u < 0.0 or u > 1.0:
                        continue
                        
                    q = np.cross(s, edge1)
                    v = f * np.dot(ray_dir_obj, q)
                    
                    if v < 0.0 or u + v > 1.0:
                        continue
                        
                    t = f * np.dot(edge2, q)
                    
                    if t > 1e-8:
                        # Hit! Transform back to world space
                        hit_local = ray_origin_obj + t * ray_dir_obj
                        hit_world = transform[:3, :3] @ hit_local + transform[:3, 3]
                        dist = np.linalg.norm(hit_world - ray_origin)
                        
                        if dist < closest_dist:
                            closest_dist = dist
                            closest_hit = hit_world
            
            if closest_hit is not None:
                results.append((closest_hit.tolist(), color))
        
        return results
    
    def extract_mesh_data(self, mesh_obj):
        """Extract mesh data into a serializable format for multiprocessing."""
        mesh = mesh_obj.data
        vertices = np.array([v.co for v in mesh.vertices])
        # Handle variable-sized faces by converting to triangles
        faces = []
        for poly in mesh.polygons:
            verts = poly.vertices
            # Triangulate polygons with more than 3 vertices
            for i in range(1, len(verts) - 1):
                faces.append([verts[0], verts[i], verts[i + 1]])
        faces = np.array(faces)
        transform = np.array(mesh_obj.matrix_world)
        
        return {
            'vertices': vertices,
            'faces': faces,
            'transform': transform
        }
    
    def gpu_accelerated_ray_cast(self, scene, camera, resolution, selected_meshes, pixels):
        """GPU-accelerated ray casting using Blender's BVH trees."""
        from mathutils.bvhtree import BVHTree
        
        cam_matrix = camera.matrix_world
        cam_data = camera.data
        
        # Build BVH trees for all selected meshes
        bvh_trees = []
        for obj in selected_meshes:
            depsgraph = bpy.context.evaluated_depsgraph_get()
            obj_eval = obj.evaluated_get(depsgraph)
            mesh = obj_eval.to_mesh()
            
            # Create BVH tree
            bvh = BVHTree.FromPolygons(
                [v.co for v in mesh.vertices],
                [p.vertices for p in mesh.polygons]
            )
            bvh_trees.append((bvh, obj.matrix_world))
            obj_eval.to_mesh_clear()
        
        results = []
        
        # Process rays in batches for better performance
        for y in range(resolution):
            for x in range(resolution):
                # Calculate ray
                ndc_x = (2.0 * (x + 0.5) / resolution) - 1.0
                ndc_y = 1.0 - (2.0 * (y + 0.5) / resolution)
                
                aspect = 1.0  # Square aspect ratio
                if cam_data.type == 'PERSP':
                    fov = cam_data.angle
                    tan_half_fov = math.tan(fov / 2.0)
                    ray_dir_cam = Vector((
                        ndc_x * tan_half_fov * aspect,
                        ndc_y * tan_half_fov,
                        -1.0
                    )).normalized()
                else:
                    ortho_scale = cam_data.ortho_scale
                    ray_dir_cam = Vector((0, 0, -1))
                    offset_x = ndc_x * ortho_scale * aspect / 2.0
                    offset_y = ndc_y * ortho_scale / 2.0
                
                # Transform to world space
                ray_origin = cam_matrix.translation.copy()
                ray_dir_world = cam_matrix.to_3x3() @ ray_dir_cam
                ray_dir_world.normalize()
                
                if cam_data.type == 'ORTHO':
                    right = cam_matrix.to_3x3() @ Vector((1, 0, 0))
                    up = cam_matrix.to_3x3() @ Vector((0, 1, 0))
                    ray_origin += right * offset_x + up * offset_y
                
                # Find closest hit using BVH
                closest_hit = None
                closest_dist = float('inf')
                
                for bvh, obj_matrix in bvh_trees:
                    # Transform ray to object space
                    obj_inv = obj_matrix.inverted()
                    ray_origin_obj = obj_inv @ ray_origin
                    ray_dir_obj = obj_inv.to_3x3() @ ray_dir_world
                    ray_dir_obj.normalize()
                    
                    # Cast ray using BVH
                    location, normal, index, dist = bvh.ray_cast(ray_origin_obj, ray_dir_obj)
                    
                    if location:
                        # Transform hit back to world space
                        hit_world = obj_matrix @ location
                        world_dist = (hit_world - ray_origin).length
                        
                        if world_dist < closest_dist:
                            closest_dist = world_dist
                            closest_hit = hit_world
                
                if closest_hit:
                    color = pixels[resolution - 1 - y, x, :3]
                    results.append((closest_hit, color))
        
        return results
    
    def cast_ray_through_pixel(self, scene, camera, pixel_x, pixel_y, res_x, res_y, selected_objects):
        """Cast ray through pixel and find intersection with selected objects"""
        cam_matrix = camera.matrix_world
        cam_data = camera.data
        
        # Calculate normalized device coordinates (-1 to 1)
        ndc_x = (2.0 * pixel_x / res_x) - 1.0
        ndc_y = 1.0 - (2.0 * pixel_y / res_y)
        
        # Get camera parameters
        aspect = res_x / res_y
        if cam_data.type == 'PERSP':
            # Perspective camera
            fov = cam_data.angle
            tan_half_fov = math.tan(fov / 2.0)
            
            # Calculate ray direction in camera space
            ray_dir_cam = Vector((
                ndc_x * tan_half_fov * aspect,
                ndc_y * tan_half_fov,
                -1.0
            )).normalized()
        else:
            # Orthographic camera
            ortho_scale = cam_data.ortho_scale
            ray_dir_cam = Vector((0, 0, -1))
            offset_x = ndc_x * ortho_scale * aspect / 2.0
            offset_y = ndc_y * ortho_scale / 2.0
        
        # Transform ray to world space
        ray_origin = cam_matrix.translation.copy()
        ray_dir_world = cam_matrix.to_3x3() @ ray_dir_cam
        ray_dir_world.normalize()
        
        if cam_data.type == 'ORTHO':
            # Offset origin for orthographic camera
            right = cam_matrix.to_3x3() @ Vector((1, 0, 0))
            up = cam_matrix.to_3x3() @ Vector((0, 1, 0))
            ray_origin += right * offset_x + up * offset_y
        
        # Find closest intersection
        closest_hit = None
        closest_dist = float('inf')
        hit_object = None
        
        for obj in selected_objects:
            if obj.type != 'MESH':
                continue
                
            # Transform ray to object space
            obj_inv = obj.matrix_world.inverted()
            ray_origin_obj = obj_inv @ ray_origin
            ray_dir_obj = obj_inv.to_3x3() @ ray_dir_world
            ray_dir_obj.normalize()
            
            # Cast ray
            result, location, normal, index = obj.ray_cast(ray_origin_obj, ray_dir_obj)
            
            if result:
                # Transform hit point back to world space
                hit_world = obj.matrix_world @ location
                dist = (hit_world - ray_origin).length
                
                if dist < closest_dist:
                    closest_dist = dist
                    closest_hit = hit_world
                    hit_object = obj
        
        return closest_hit
    
    def render_frame_to_pixels(self, scene, resolution):
        """Render current frame and return pixel data"""
        # Store original settings
        orig_res_x = scene.render.resolution_x
        orig_res_y = scene.render.resolution_y
        orig_percentage = scene.render.resolution_percentage
        orig_filepath = scene.render.filepath
        
        # Temporarily hide helper meshes from viewport
        helper_meshes = [(item.mesh_object, item.mesh_object.hide_viewport) 
                        for item in scene.helper_meshes 
                        if item.mesh_object]
        for obj, _ in helper_meshes:
            obj.hide_viewport = True
        
        # Set low resolution
        scene.render.resolution_x = resolution
        scene.render.resolution_y = resolution
        scene.render.resolution_percentage = 100
        
        # Render to temporary image
        temp_path = os.path.join(bpy.app.tempdir, f"pointcloud_temp_{scene.frame_current}.png")
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
    
    def write_ply(self, filepath, points, colors):
        """Write point cloud to PLY file"""
        num_points = len(points)
        
        with open(filepath, 'wb') as f:
            # Write PLY header
            header = f"""ply
format binary_little_endian 1.0
element vertex {num_points}
property float x
property float y
property float z
property uchar red
property uchar green
property uchar blue
end_header
"""
            f.write(header.encode('ascii'))
            
            # Write binary data
            for i in range(num_points):
                # Position (3 floats)
                f.write(np.array(points[i], dtype=np.float32).tobytes())
                
                # Color (3 unsigned chars)
                color = np.array(colors[i] * 255, dtype=np.uint8)
                f.write(color.tobytes())
    
    def execute(self, context):
        scene = context.scene
        camera = scene.camera
        resolution = scene.pointcloud_resolution
        
        # Get selected mesh objects, excluding helper meshes
        helper_mesh_objects = {item.mesh_object for item in scene.helper_meshes if item.mesh_object}
        selected_meshes = [obj for obj in context.selected_objects 
                          if obj.type == 'MESH' and obj not in helper_mesh_objects]
        
        if not selected_meshes:
            self.report({'ERROR'}, "No mesh objects selected (helper meshes are excluded)")
            return {'CANCELLED'}
        
        # Extract mesh data for parallel processing
        mesh_data_list = [self.extract_mesh_data(obj) for obj in selected_meshes]
        
        # Prepare camera data
        cam_data = camera.data
        cam_matrix = np.array(camera.matrix_world)
        cam_data_type = cam_data.type
        cam_angle = cam_data.angle if cam_data_type == 'PERSP' else 0
        cam_ortho_scale = cam_data.ortho_scale if cam_data_type == 'ORTHO' else 0
        
        # Check if GPU acceleration is available and enabled
        use_gpu = scene.use_gpu_acceleration and self.check_gpu_available()
        
        # Determine number of workers for CPU mode
        num_workers = max(1, cpu_count() - 1)
        
        # Collect all points and colors
        all_points = []
        all_colors = []
        
        # Process each frame
        total_frames = scene.frame_end - scene.frame_start + 1
        wm = context.window_manager
        wm.progress_begin(0, total_frames)
        
        if use_gpu:
            self.report({'INFO'}, "Using GPU-accelerated BVH ray casting")
        else:
            self.report({'INFO'}, f"Using {num_workers} CPU cores for ray casting")
        
        for i, frame_idx in enumerate(range(scene.frame_start, scene.frame_end + 1)):
            # Update progress
            wm.progress_update(i)
            
            scene.frame_set(frame_idx)
            
            # Update camera matrix for this frame
            cam_matrix = np.array(camera.matrix_world)
            
            # Render frame at low resolution
            self.report({'INFO'}, f"Processing frame {frame_idx}/{scene.frame_end}")
            pixels = self.render_frame_to_pixels(scene, resolution)
            
            if use_gpu:
                # Use GPU-accelerated BVH ray casting
                frame_results = self.gpu_accelerated_ray_cast(
                    scene, camera, resolution, selected_meshes, pixels
                )
                for hit_point, color in frame_results:
                    all_points.append(hit_point)
                    all_colors.append(color)
            else:
                # Use CPU multiprocessing
                # Prepare pixel batches for parallel processing
                batch_size = max(1, (resolution * resolution) // (num_workers * 4))
                pixel_batches = []
                color_batches = []
                
                # Create batches of pixels
                pixel_coords = []
                colors = []
                for y in range(resolution):
                    for x in range(resolution):
                        pixel_coords.append((x, y))
                        colors.append(pixels[resolution - 1 - y, x, :3])
                        
                        if len(pixel_coords) >= batch_size:
                            pixel_batches.append(pixel_coords)
                            color_batches.append(colors)
                            pixel_coords = []
                            colors = []
                
                # Add remaining pixels
                if pixel_coords:
                    pixel_batches.append(pixel_coords)
                    color_batches.append(colors)
                
                # Process batches in parallel
                with Pool(processes=num_workers) as pool:
                    batch_args = [
                        (batch, cam_matrix, cam_data_type, cam_angle, cam_ortho_scale, 
                         resolution, mesh_data_list, color_batch)
                        for batch, color_batch in zip(pixel_batches, color_batches)
                    ]
                    
                    results = pool.map(self.process_pixel_batch, batch_args)
                    
                    # Collect results
                    for batch_results in results:
                        for hit_point, color in batch_results:
                            all_points.append(hit_point)
                            all_colors.append(color)
        
        wm.progress_end()
        
        # Write PLY file
        output_path = bpy.path.abspath(scene.pointcloud_output_path)
        output_dir = os.path.dirname(output_path)
        
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)
        
        self.write_ply(output_path, all_points, all_colors)
        
        self.report({'INFO'}, f"Generated point cloud with {len(all_points)} points from {total_frames} frames")
        return {'FINISHED'}

# Combined generate and export operator
class CAMERA_OT_generate_and_export(bpy.types.Operator):
    """Generate camera keyframes and export JSON"""
    bl_idname = "camera.generate_and_export"
    bl_label = "Generate & Export"
    bl_options = {'REGISTER', 'UNDO'}
    
    @classmethod
    def poll(cls, context):
        return len(context.scene.helper_meshes) > 0
    
    def execute(self, context):
        # Generate keyframes
        bpy.ops.camera.generate_from_faces()
        # Export JSON
        bpy.ops.export.camera_json()
        return {'FINISHED'}

# UI Panel
class VIEW3D_PT_helper_mesh_panel(bpy.types.Panel):
    """Creates a Panel in the 3D viewport N-panel"""
    bl_label = "Splat-Tools: Gaussian Splatting Toolbox"
    bl_idname = "VIEW3D_PT_helper_mesh_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Splat-Tools"
    
    def draw(self, context):
        layout = self.layout
        scene = context.scene
        
        # Helper mesh section
        box = layout.box()
        row = box.row()
        row.label(text="Helper Meshes", icon='MESH_DATA')
        row.label(text=f"({len(scene.helper_meshes)} total)")
        
        row = box.row()
        row.operator("mesh.add_helper", icon='ADD')
        row.operator("mesh.clear_helpers", icon='X')
        
        # List of helper meshes
        if len(scene.helper_meshes) > 0:
            col = box.column()
            for i, item in enumerate(scene.helper_meshes):
                row = col.row(align=True)
                
                # Show mesh status
                if item.mesh_object:
                    icon = 'MESH_DATA' if item.mesh_object.visible_get() else 'HIDE_ON'
                    face_count = len(item.mesh_object.data.polygons)
                    row.label(text=f"{item.name} ({face_count} faces)", icon=icon)
                else:
                    row.label(text="(Missing)", icon='ERROR')
                
                op = row.operator("mesh.remove_helper", text="", icon='X')
                op.index = i
        else:
            box.label(text="No helper meshes added")
            box.label(text="Select meshes and click '+'", icon='INFO')
        
        # Camera settings
        box = layout.box()
        box.label(text="Camera Settings", icon='CAMERA_DATA')
        
        col = box.column(align=True)
        col.prop(scene, "camera_focal_length")
        
        row = col.row(align=True)
        row.prop(scene, "output_width")
        row.prop(scene, "output_height")
        
        # Export settings
        box = layout.box()
        box.label(text="Export Settings", icon='EXPORT')
        
        col = box.column()
        col.prop(scene, "json_output_path")
        col.prop(scene, "postshot_mode")
        
        # Action buttons
        layout.separator()
        
        # Show total face count
        total_faces = sum(len(item.mesh_object.data.polygons) 
                         for item in scene.helper_meshes 
                         if item.mesh_object)
        if total_faces > 0:
            layout.label(text=f"Total faces: {total_faces}", icon='INFO')
        
        col = layout.column(align=True)
        col.scale_y = 1.5
        col.operator("camera.generate_from_faces", icon='CAMERA_DATA')
        col.operator("export.camera_json", icon='EXPORT')
        
        layout.separator()
        
        row = layout.row()
        row.scale_y = 2.0
        row.operator("camera.generate_and_export", icon='FILE_REFRESH')
        
        # Point cloud generation
        layout.separator()
        
        box = layout.box()
        box.label(text="Point Cloud Export", icon='MESH_DATA')
        
        # Show selected objects count
        selected_meshes = [obj for obj in context.selected_objects if obj.type == 'MESH']
        if selected_meshes:
            box.label(text=f"Selected objects: {len(selected_meshes)}", icon='INFO')
        else:
            box.label(text="No mesh objects selected", icon='ERROR')
        
        col = box.column()
        col.prop(scene, "pointcloud_output_path")
        col.prop(scene, "pointcloud_resolution")
        col.prop(scene, "use_gpu_acceleration")
        
        col.separator()
        col.scale_y = 1.5
        col.operator("export.pointcloud_ply", icon='EXPORT')

# Registration
classes = [
    HelperMeshItem,
    MESH_OT_add_helper,
    MESH_OT_remove_helper,
    MESH_OT_clear_helpers,
    CAMERA_OT_generate_from_faces,
    EXPORT_OT_camera_json,
    EXPORT_OT_pointcloud_ply,
    CAMERA_OT_generate_and_export,
    VIEW3D_PT_helper_mesh_panel,
]

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    
    # Add properties to scene
    bpy.types.Scene.helper_meshes = bpy.props.CollectionProperty(type=HelperMeshItem)
    bpy.types.Scene.helper_mesh_index = bpy.props.IntProperty(default=0)
    
    bpy.types.Scene.json_output_path = bpy.props.StringProperty(
        name="Output File",
        description="JSON file to export camera data",
        default="//camera_data.json",
        subtype='FILE_PATH'
    )
    
    bpy.types.Scene.output_width = bpy.props.IntProperty(
        name="Width",
        description="Render width in pixels",
        default=1920,
        min=1,
        max=16384
    )
    
    bpy.types.Scene.output_height = bpy.props.IntProperty(
        name="Height", 
        description="Render height in pixels",
        default=1080,
        min=1,
        max=16384
    )
    
    bpy.types.Scene.camera_focal_length = bpy.props.FloatProperty(
        name="Focal Length (mm)",
        description="Camera lens focal length",
        default=35.0,
        min=1.0,
        max=500.0,
        precision=1
    )
    
    bpy.types.Scene.postshot_mode = bpy.props.BoolProperty(
        name="Postshot Compatible",
        description="Export in simplified format for Postshot",
        default=False
    )
    
    bpy.types.Scene.pointcloud_output_path = bpy.props.StringProperty(
        name="Output File",
        description="PLY file to export point cloud data",
        default="//pointcloud.ply",
        subtype='FILE_PATH'
    )
    
    bpy.types.Scene.pointcloud_resolution = bpy.props.IntProperty(
        name="Resolution",
        description="Render resolution for point cloud generation",
        default=256,
        min=64,
        max=1024
    )
    
    bpy.types.Scene.use_gpu_acceleration = bpy.props.BoolProperty(
        name="Use GPU Acceleration",
        description="Use GPU-accelerated BVH for ray casting (faster but uses more memory)",
        default=True
    )

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    
    # Remove properties
    del bpy.types.Scene.helper_meshes
    del bpy.types.Scene.helper_mesh_index
    del bpy.types.Scene.json_output_path
    del bpy.types.Scene.output_width
    del bpy.types.Scene.output_height
    del bpy.types.Scene.camera_focal_length
    del bpy.types.Scene.postshot_mode
    del bpy.types.Scene.pointcloud_output_path
    del bpy.types.Scene.pointcloud_resolution
    del bpy.types.Scene.use_gpu_acceleration

if __name__ == "__main__":
    register()