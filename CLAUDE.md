# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Splat Tools is a Blender add-on for generating camera paths and point clouds for Gaussian Splatting workflows. It allows users to define camera positions based on mesh faces, export camera data in JSON format, and generate colored point clouds in PLY format compatible with photogrammetry pipelines.

### Testing
- Manual testing in Blender's 3D viewport
- Enable Developer Extras in Blender preferences for addon reload functionality
- Use Blender's System Console for debugging output

## Architecture

### Core Components

1. **Property Groups** (lines 14-21)
   - `HelperMeshItem`: Stores references to mesh objects used as camera position helpers
   - Properties: `mesh_object` (pointer to mesh), `name` (string)

2. **Operators** (lines 24-860)
   - `MESH_OT_add_helper`: Add mesh objects to helper list (lines 24-55)
   - `MESH_OT_remove_helper`: Remove specific helper mesh (lines 58-82)
   - `MESH_OT_clear_helpers`: Clear all helper meshes (lines 85-104)
   - `CAMERA_OT_generate_from_faces`: Create camera keyframes from mesh faces (lines 107-286)
   - `EXPORT_OT_camera_json`: Export camera data to JSON (lines 289-443)
   - `EXPORT_OT_pointcloud_ply`: Generate colored point cloud PLY (lines 446-840)
   - `CAMERA_OT_generate_and_export`: Combined generate + export (lines 843-860)

3. **UI Panel** (lines 863-973)
   - `VIEW3D_PT_helper_mesh_panel`: Main panel in 3D viewport N-panel
   - Located under "Splat-Tools" category
   - Shows helper meshes, camera settings, export settings, and point cloud options

4. **Registration** (lines 976-1083)
   - Scene properties for configuration
   - Blender registration/unregistration handlers
   - Custom properties added to bpy.types.Scene

### Key Algorithms

1. **Camera Generation from Faces**:
   - Iterates through each face of helper meshes
   - Positions camera at face center
   - Orients camera opposite to face normal
   - Creates keyframe for each face position
   - Optional interior camera detection using odd-even ray casting rule

2. **Interior Camera Detection** (`is_camera_inside_mesh`):
   - Uses odd-even rule to detect if camera is inside a mesh
   - Casts rays and counts intersections
   - Odd number of intersections = inside mesh
   - Excludes helper meshes from detection

3. **Camera Export Format**:
   - Standard mode: Full camera parameters with transform matrices
   - Postshot Compatible mode: Simplified format for specific pipeline
   - Includes intrinsics (focal length, FOV) and extrinsics (4x4 transform matrices)
   - Computes scene AABB scale for normalization

4. **Point Cloud Generation**:
   - Renders each camera frame at low resolution
   - Ray casts through each pixel to find mesh intersections
   - Supports GPU-accelerated BVH ray casting
   - Exports colored PLY with Y-up coordinate system (converted from Blender's Z-up)

### Data Flow
1. User adds mesh objects as "helper meshes"
2. Helper meshes are hidden from render automatically
3. Camera keyframes generated from face positions
4. Camera data exported to JSON for external processing
5. Optional: Generate point cloud from selected meshes using camera views

## Important Considerations

- Always test in Blender after making changes
- Preserve Blender API compatibility (currently targets 4.2.0+)
- Maintain JSON export format compatibility for downstream tools
- Helper meshes should remain hidden from render to avoid appearing in output
- Camera orientation follows the convention: looking opposite to face normal
- Point cloud coordinate system conversion: Blender's Z-up to Y-up for compatibility
- GPU acceleration requires gpu module and BVH tree support
- Temporary files are created in Blender's temp directory during point cloud generation

## Scene Properties Added

- `helper_meshes`: Collection of HelperMeshItem
- `helper_mesh_index`: Active index for UI list
- `json_output_path`: Path for camera JSON export
- `output_width/height`: Render resolution settings
- `camera_focal_length`: Focal length in mm
- `postshot_mode`: Boolean for simplified export format
- `pointcloud_output_path`: Path for PLY export
- `pointcloud_resolution`: Resolution for point cloud rendering (64-1024)
- `use_gpu_acceleration`: Toggle GPU-accelerated BVH
- `skip_interior_cameras`: Toggle interior camera detection

## Dependencies

- `bpy`: Blender Python API
- `numpy`: For efficient array operations
- `mathutils`: Blender's math utilities
- `gpu` and `gpu_extras`: For GPU acceleration
- Standard library: `os`, `json`, `math`, `collections.defaultdict`