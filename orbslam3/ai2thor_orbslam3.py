from time import time
from functools import reduce
from tempfile import mkstemp
import os
import math
import yaml
import numpy as np
import matplotlib.pyplot as plt

import orbslam3
from ai2thor.controller import Controller


np.set_printoptions(suppress=True)

def compute_pose(agent_position, agent_rotation):
    pose = np.eye(4, dtype=np.float32)
    pose[:3, 3] = np.array([agent_position[d] for d in 'xyz'])
    pose[:3, :3] = euler_angles_to_matrix(np.deg2rad(
        np.array([agent_rotation[d] for d in 'zyx'])
    ), 'ZYX')
    return pose

def state_to_pose(agent_state):
    agent_position = {k : agent_state[k] for k in 'xyz'}
    agent_rotation = {k : agent_state['rotation'][k] for k in 'xyz'}
    pose = compute_pose(agent_position, agent_rotation)
    return pose


# Modified from pytorch3d.transforms
def euler_angles_to_matrix(euler_angles, convention):

    def _axis_angle_rotation(axis, angle):
        cos, sin = np.cos(angle), np.sin(angle)
        one, zero = np.ones_like(angle), np.zeros_like(angle)
        if axis == "X":
            R_flat = (one, zero, zero, zero, cos, -sin, zero, sin, cos)
        elif axis == "Y":
            R_flat = (cos, zero, sin, zero, one, zero, -sin, zero, cos)
        elif axis == "Z":
            R_flat = (cos, -sin, zero, sin, cos, zero, zero, zero, one)
        return np.stack(R_flat, -1).reshape(angle.shape + (3, 3))

    matrices = map(_axis_angle_rotation, convention, euler_angles)
    return reduce(np.matmul, matrices)
##

def init_pose(event):
    pose = np.eye(4, dtype=np.float32)
    pose[:3, 3] = np.array([
        event.metadata['agent']['position']['x'],
        event.metadata['agent']['position']['y'],
        event.metadata['agent']['position']['z'],
    ])
    angles = np.array([
        event.metadata['agent']['rotation']['z'],
        event.metadata['agent']['rotation']['y'],
        event.metadata['agent']['rotation']['x']
    ])
    pose[:3, :3] = euler_angles_to_matrix(np.deg2rad(angles), 'ZYX')
    return pose

# check Camera.fps, Camera.bf, ThDepth, DepthMapFactor
# parameterize ORBextractor
def init_settings(event):
    w, h = event.metadata['screenWidth'], event.metadata['screenHeight']
    fov = event.metadata['fov']
    f_x = w / (2 * math.tan(math.radians(fov / 2)))
    f_y = h / (2 * math.tan(math.radians(fov / 2)))
    c_x, c_y = w / 2, h / 2
    return {
        'Camera.type': 'PinHole',
        'Camera.fx': f_x, 'Camera.fy': f_y, 'Camera.cx': c_x, 'Camera.cy': c_y,
        'Camera.k1': 0.0, 'Camera.k2': 0.0, 'Camera.p1': 0.0, 'Camera.p2': 0.0,
        'Camera.width': w, 'Camera.height': h, 'Camera.fps': 0.0, 'Camera.bf': 40.0, 'Camera.RGB': 1,
        'ThDepth': 200.0, 'DepthMapFactor': 1.0,
        'ORBextractor.nFeatures': 1000, 'ORBextractor.scaleFactor': 1.2, 'ORBextractor.nLevels': 8,
        'ORBextractor.iniThFAST': 20, 'ORBextractor.minThFAST': 1,
        'Viewer.KeyFrameSize': 0.05, 'Viewer.KeyFrameLineWidth': 1, 'Viewer.GraphLineWidth': 0.9,
        'Viewer.PointSize':2, 'Viewer.CameraSize': 0.08, 'Viewer.CameraLineWidth': 3,
        'Viewer.ViewpointX': 0, 'Viewer.ViewpointY': -0.7, 'Viewer.ViewpointZ': -1.8, 'Viewer.ViewpointF': 500
    }

def init_slam(controller, vocab_file, use_viewer):
    event = controller.step(action='Pass')
    _, settings_file = mkstemp()
    with open(settings_file, 'w') as file:
        file.write('%YAML:1.0')
        file.write(yaml.dump(init_settings(event)))
    slam_system = orbslam3.SLAM(vocab_file, settings_file, 'rgbd', init_pose(event), use_viewer)
    os.remove(settings_file)
    return slam_system

class ORBSLAM3Controller(Controller):
    def __init__(self, vocab_file, use_viewer=True, **kwargs):
        self.slam_system = None
        super().__init__(**kwargs)

        self.slam_system = init_slam(super(), vocab_file, use_viewer)

        self.gt_trajectory = {'x' : [], 'z' : []}
        self.slam_trajectory = {'x' : [], 'z' : []}

        self.frame_counter = 0
        self.time_elapsed = 0.0

    def step(self, **kwargs):
        start = time()
        event = super().step(**kwargs)

        if self.slam_system is not None:
            self.gt_trajectory['x'].append(event.metadata['agent']['position']['x'])
            self.gt_trajectory['z'].append(event.metadata['agent']['position']['z'])

            self.slam_system.track(event.frame, event.depth_frame)
            pose = self.slam_system.get_world_pose()

            self.slam_trajectory['x'].append(pose[0, 3])
            self.slam_trajectory['z'].append(pose[2, 3])

            self.frame_counter += 1
            self.time_elapsed += time() - start

        return event

    def stop(self, **kwargs):
        super().stop(**kwargs)
        self.slam_system.shutdown()

    def vis_trajectory(self, file):
        plt.scatter(self.gt_trajectory['x'], self.gt_trajectory['z'])
        plt.scatter(self.slam_trajectory['x'], self.slam_trajectory['z'])
        plt.savefig(file)

    def fps(self):
        return self.frame_counter / self.time_elapsed
