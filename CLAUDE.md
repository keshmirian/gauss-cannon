# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Gauss Cannon is a Blender add-on for generating camera paths and point clouds for Gaussian Splatting workflows. It allows users to define camera positions based on mesh faces, export camera data in JSON format, and generate colored point clouds in PLY format compatible with photogrammetry pipelines.

## Development Commands

### Installation and Testing
- **Install in Blender**: Copy the `addon` folder to Blender's addons directory or use Edit > Preferences > Add-ons > Install from File
- **Enable Developer Extras**: Edit > Preferences > Interface > Developer Extras (required for addon reload)
- **Reload Addon**: F3 > "Reload Scripts" in Blender after code changes
- **Debug Output**: Window > Toggle System Console (Windows) or run Blender from terminal to see print statements

### Common Development Workflow
1. Edit code in the `addon/` directory
2. In Blender: F3 > "Reload Scripts" to reload the addon
3. Test functionality in 3D viewport > N-panel > "Gauss Cannon" tab
4. Check System Console for debug output

## Architecture

### Module Structure
```
addon/
├── __init__.py              # Entry point, class registration
├── blender_manifest.toml    # Addon metadata (Blender 4.2+)
├── properties.py            # Scene properties and HelperMeshItem PropertyGroup
├── operators/
│   ├── __init__.py          # Operator exports
│   ├── helper_mesh.py       # MESH_OT_add/remove/clear_helpers
│   ├── camera.py            # CAMERA_OT_generate_from_faces, CAMERA_OT_generate_and_export
│   ├── export_camera.py     # EXPORT_OT_camera_json
│   └── export_pointcloud.py # EXPORT_OT_pointcloud_ply
├── ui/
│   ├── __init__.py          # UI exports
│   └── panels.py            # VIEW3D_PT_helper_mesh_panel
└── utils/
    ├── __init__.py          # Utility exports
    ├── ray_casting.py       # Interior detection, pixel ray casting, GPU BVH
    └── coordinate_systems.py # Y-up/Z-up conversion, PLY writing utilities
```

### Key Components

**Properties** (`properties.py`):
- `HelperMeshItem`: PropertyGroup storing mesh object references for camera position templates
- Scene properties for export settings (resolution, focal length, export mode, coordinate system)

**Operators** (`operators/`):
- Helper mesh management: Add/remove/clear meshes from the helper list
- Camera generation: Creates keyframes at each helper mesh face center, oriented opposite to face normal
- Export: JSON camera data (LichtFeld/Postshot formats) and PLY point clouds

**Utilities** (`utils/`):
- `is_camera_inside_mesh()`: Odd-even ray casting rule for interior detection
- `cast_ray_through_pixel()`: Single ray casting for point cloud generation
- `gpu_accelerated_ray_cast()`: BVH-based batch ray casting for performance
- `convert_coordinate_system()`: Blender Z-up to Y-up matrix/point conversion

### Data Flow
1. User adds mesh objects as "helper meshes" (auto-hidden from render)
2. Camera keyframes generated from face positions
3. Camera data exported to JSON for external processing
4. Optional: Generate point cloud from selected meshes using camera views

## Key Algorithms

**Interior Camera Detection** (`utils/ray_casting.py:is_camera_inside_mesh`):
- Casts ray in +X direction from camera position
- Counts mesh intersections; odd count = inside mesh
- Excludes helper meshes from detection

**Point Cloud Generation** (`operators/export_pointcloud.py`):
- Renders each camera frame at configurable resolution
- Ray casts through each pixel to find mesh intersections
- GPU acceleration uses BVH trees for batch processing

**Coordinate Conversion** (`utils/coordinate_systems.py`):
- Blender uses Z-up; most external tools use Y-up
- Matrix conversion: `conversion_matrix @ transform_matrix`
- Point conversion: `[x, z, y]` for Y-up output

## Export Format Details

**LichtFeld Studio JSON**: Full camera parameters with `fl_x`, `fl_y`, transform matrices
**Postshot JSON**: Simplified format without focal length fields
**PLY Point Cloud**: Binary little-endian format with xyz positions + RGB colors

## Dependencies

- Blender 4.2.0+ Python API (`bpy`, `mathutils`, `gpu`)
- `numpy`: Array operations for PLY binary output
- Standard library: `os`, `json`, `math`
