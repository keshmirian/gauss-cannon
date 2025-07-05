# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Splat Tools is a Blender add-on for generating camera paths for Gaussian Splatting workflows. It allows users to define camera positions based on mesh faces and export camera data in JSON format compatible with photogrammetry pipelines.

### Testing
- Manual testing in Blender's 3D viewport
- Enable Developer Extras in Blender preferences for addon reload functionality
- Use Blender's System Console for debugging output

## Architecture

### Core Components

1. **Property Groups** (lines 11-18)
   - `HellerMeshItem`: Stores references to mesh objects used as camera position helpers

2. **Operators** (lines 20-430)
   - `MESH_OT_add_helper`: Add mesh objects to helper list
   - `MESH_OT_remove_helper`: Remove specific helper mesh
   - `MESH_OT_clear_helpers`: Clear all helper meshes
   - `CAMERA_OT_generate_from_faces`: Create camera keyframes from mesh faces
   - `EXPORT_OT_camera_json`: Export camera data to JSON
   - `CAMERA_OT_generate_and_export`: Combined generate + export

3. **UI Panel** (lines 432-481)
   - `VIEW3D_PT_face_camera_generator`: Main panel in 3D viewport N-panel
   - Located under "Splat-Tools" category

4. **Registration** (lines 483-522)
   - Scene properties for configuration
   - Blender registration/unregistration handlers

### Key Algorithms

1. **Camera Generation from Faces**:
   - Iterates through each face of helper meshes
   - Positions camera at face center
   - Orients camera opposite to face normal
   - Creates keyframe for each face position

2. **Camera Export Format**:
   - Standard mode: Full camera parameters with transform matrices
   - Postshot Compatible mode: Simplified format for specific pipeline
   - Includes intrinsics (focal length, FOV) and extrinsics (4x4 transform matrices)

### Data Flow
1. User adds mesh objects as "helper meshes"
2. Helper meshes are hidden from render automatically
3. Camera keyframes generated from face positions
4. Camera data exported to JSON for external processing

## Important Considerations

- Always test in Blender after making changes
- Preserve Blender API compatibility (currently targets 4.2.0+)
- Maintain JSON export format compatibility for downstream tools
- Helper meshes should remain hidden from render to avoid appearing in output
- Camera orientation follows the convention: looking opposite to face normal