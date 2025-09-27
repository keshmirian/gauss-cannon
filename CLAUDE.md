# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SplatKit is a Blender add-on for generating camera paths and point clouds for Gaussian Splatting workflows. It allows users to define camera positions based on mesh faces, export camera data in JSON format, and generate colored point clouds in PLY format compatible with photogrammetry pipelines.

## Development Commands

### Installation and Testing
- **Install in Blender**: Copy the `addon` folder to Blender's addons directory or use Edit > Preferences > Add-ons > Install from File
- **Enable Developer Extras**: Edit > Preferences > Interface > Developer Extras (required for addon reload)
- **Reload Addon**: F3 > "Reload Scripts" in Blender after code changes
- **Debug Output**: Window > Toggle System Console (Windows) or run Blender from terminal to see print statements

### Common Development Workflows
1. Edit code in `addon/__init__.py`
2. In Blender: F3 > "Reload Scripts" to reload the addon
3. Test functionality in 3D viewport > N-panel > "SplatKit" tab
4. Check System Console for debug output

## Architecture

### File Structure
- `addon/__init__.py`: Main addon implementation (1218 lines)
- `addon/blender_manifest.toml`: Addon metadata and configuration
- Main code location: All functionality in single `__init__.py` file

### Core Components

1. **Property Groups** (lines 11-17)
   - `HelperMeshItem`: Stores references to mesh objects used as camera position helpers
   - Properties: `mesh_object` (pointer to mesh), `name` (string)

2. **Operators** (lines 21-967)
   - `MESH_OT_add_helper`: Add mesh objects to helper list (lines 21-61)
   - `MESH_OT_remove_helper`: Remove specific helper mesh (lines 64-93)
   - `MESH_OT_clear_helpers`: Clear all helper meshes (lines 96-118)
   - `CAMERA_OT_generate_from_faces`: Create camera keyframes from mesh faces (lines 121-320)
   - `EXPORT_OT_camera_json`: Export camera data to JSON (lines 323-536)
   - `EXPORT_OT_pointcloud_ply`: Generate colored point cloud PLY (lines 539-964)
   - `CAMERA_OT_generate_and_export`: Combined generate + export (lines 967-984)

3. **UI Panel** (lines 987-1127)
   - `VIEW3D_PT_helper_mesh_panel`: Main panel in 3D viewport N-panel
   - Located under "SplatKit" category
   - Shows helper meshes, camera settings, export settings, and point cloud options

4. **Registration** (lines 1130-1218)
   - Scene properties for configuration
   - Blender registration/unregistration handlers
   - Custom properties added to bpy.types.Scene

### Key Algorithms

1. **Camera Generation from Faces** (`CAMERA_OT_generate_from_faces.execute`):
   - Iterates through each face of helper meshes
   - Positions camera at face center
   - Orients camera opposite to face normal
   - Creates keyframe for each face position
   - Optional interior camera detection using odd-even ray casting rule

2. **Interior Camera Detection** (`is_camera_inside_mesh`, lines 200-235):
   - Uses odd-even rule to detect if camera is inside a mesh
   - Casts rays and counts intersections
   - Odd number of intersections = inside mesh
   - Excludes helper meshes from detection

3. **Camera Export Format** (`EXPORT_OT_camera_json`):
   - LichtFeld Studio Compatible mode: Full camera parameters with transform matrices
   - Postshot Compatible mode: Simplified format for specific pipeline
   - Standard mode: Alternative export format
   - Includes intrinsics (focal length, FOV) and extrinsics (4x4 transform matrices)
   - Computes scene AABB scale for normalization

4. **Point Cloud Generation** (`EXPORT_OT_pointcloud_ply`):
   - Renders each camera frame at configurable resolution
   - Ray casts through each pixel to find mesh intersections
   - Supports GPU-accelerated BVH ray casting (lines 697-768)
   - Exports colored PLY with configurable coordinate system (Y-up or Z-up)

### Data Flow
1. User adds mesh objects as "helper meshes"
2. Helper meshes are hidden from render automatically
3. Camera keyframes generated from face positions
4. Camera data exported to JSON for external processing
5. Optional: Generate point cloud from selected meshes using camera views

## Scene Properties Added

- `helper_meshes`: Collection of HelperMeshItem
- `helper_mesh_index`: Active index for UI list
- `json_output_path`: Path for camera JSON export
- `output_width/height`: Render resolution settings
- `camera_focal_length`: Focal length in mm
- `export_mode`: Export format selection (STANDARD, POSTSHOT, LICHTFELD)
- `coordinate_system`: Coordinate system for exports (Y_UP, Z_UP)
- `pointcloud_output_path`: Path for PLY export
- `pointcloud_resolution`: Resolution for point cloud rendering (64-1024)
- `use_gpu_acceleration`: Toggle GPU-accelerated BVH
- `skip_interior_cameras`: Toggle interior camera detection

## Important Implementation Details

### Helper Mesh Management
- Helper meshes are automatically hidden from render when added (line 57)
- Helper meshes are excluded from point cloud generation (lines 850-857)
- Removing helper mesh restores render visibility (line 81)

### Camera Generation Specifics
- Creates or reuses existing camera object named "Camera" (lines 162-168)
- Sets animation keyframes with linear interpolation (lines 305-308)
- Adjusts timeline to encompass all generated frames (lines 310-313)

### Point Cloud Processing
- Temporary render files created in Blender's temp directory (lines 558-579)
- Uses persistent data for faster animation rendering (lines 883-884)
- GPU acceleration uses batch processing for efficiency (lines 697-768)
- Coordinate conversion handled during PLY writing (lines 824-835)

### Export Format Details
- JSON export includes both camera intrinsics and extrinsics
- Transform matrices use column-major ordering for compatibility
- AABB scale computed from all mesh vertices for scene normalization
- Postshot mode exports simplified format without certain fields

### Performance Tips
- Use low-poly meshes as helpers for faster processing (icospheres work great)
- Enable GPU acceleration for point cloud generation
- Start with low resolution (8-16) for testing
- Use "persistent render data" setting for rendering speed-up
- Helper face count - invalid cameras = camera count

### Troubleshooting Common Issues
- **No cameras generated**: Ensure helper meshes are added and have faces
- **GPU acceleration not working**: Check Blender GPU compute settings
- **Interior cameras still appearing**: Enable "Skip Interior Cameras" and ensure meshes are manifold

## Dependencies

- `bpy`: Blender Python API
- `numpy`: For efficient array operations
- `mathutils`: Blender's math utilities
- `gpu` and `gpu_extras`: For GPU acceleration
- Standard library: `os`, `json`, `math`, `collections.defaultdict`

## Addon Configuration

The addon manifest (`blender_manifest.toml`) specifies:
- Minimum Blender version: 4.2.0
- Required permissions: File access for writing camera/point cloud data
- Tags: Import-Export, Render
- License: MIT