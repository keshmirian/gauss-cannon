# Splat Tools
Developed by Arash Keshmirian

## Purpose
Splat Tools is a comprehensive Blender add-on designed for generating camera paths and point clouds for Gaussian Splatting workflows. It provides an intuitive interface for defining camera positions based on mesh faces and exporting camera data in JSON format compatible with photogrammetry pipelines.

## Features

### Camera Path Generation
- **Helper Mesh System**: Use any mesh object as a template for camera positions
- **Face-Based Camera Placement**: Automatically generates camera keyframes at each face center
- **Smart Camera Orientation**: Cameras face opposite to face normals for optimal coverage
- **Interior Camera Detection**: Option to skip cameras detected inside scene meshes

### Export Capabilities
- **Camera JSON Export**: Exports camera intrinsics and extrinsics in standard JSON format
- **Postshot Compatibility Mode**: Simplified export format for specific pipeline requirements
- **Raytracing-based Point Cloud Generation**: Converts selected meshes to accurately-colored PLY point clouds
- **GPU-Accelerated Ray Casting**: Fast point cloud generation using Blender's BVH trees

### User Interface
- **Integrated Panel**: Clean UI panel in the 3D viewport's N-panel under "Splat-Tools"
- **Real-time Feedback**: Shows face counts and total camera positions
- **Batch Operations**: Combined generate & export functionality

## Usage

### Basic Workflow

1. **Add Helper Meshes**
   - Select mesh objects in your scene
   - Click the "+" button in the Splat-Tools panel
   - Helper meshes are automatically hidden from render

2. **Configure Camera Settings**
   - Set focal length (default: 35mm)
   - Set output resolution (default: 1920x1080)
   - Enable "Skip Interior Cameras" to avoid cameras inside meshes

3. **Generate Camera Path**
   - Click "Generate Camera Keyframes"
   - Cameras are created at each face center of helper meshes
   - Timeline is automatically adjusted to show all keyframes

4. **Export Camera Data**
   - Set output path for JSON file
   - Click "Export Camera JSON"
   - Enable "Postshot Compatible" for simplified format if needed

### Point Cloud Export

1. **Select Target Meshes**
   - Select the mesh objects you want to convert (excluding helper meshes)
   - Ensure camera path is already generated

2. **Configure Point Cloud Settings**
   - Set output PLY file path
   - Choose resolution (64-1024, default: 256)
   - Enable GPU acceleration for faster processing

3. **Generate Point Cloud**
   - Click "Generate Point Cloud PLY from Selected"
   - Progress is shown during multi-frame processing
   - Output includes color information from rendered views

## Technical Details

### Camera JSON Format

Standard mode includes:
- `aabb_scale`: Scene bounding box scale
- `w`, `h`: Resolution
- `fl_x`, `fl_y`: Focal lengths in pixels
- `cx`, `cy`: Principal point
- `camera_angle_x`, `camera_angle_y`: Field of view
- `frames`: Array of camera poses with 4x4 transform matrices

### Point Cloud Format

- Standard PLY format with vertex colors
- Coordinate system: Y-up (converted from Blender's Z-up)
- Binary little-endian encoding for efficiency

## Requirements

- Blender 4.2.0 or higher
- NumPy (included with Blender)
- GPU support recommended for point cloud generation

## Tips

- Use low-poly meshes as helpers for faster processing
- Helper meshes are automatically excluded from renders
- Point cloud resolution affects quality vs. processing time trade-off