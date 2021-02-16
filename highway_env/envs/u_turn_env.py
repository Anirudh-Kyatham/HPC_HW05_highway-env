%%writefile /content/highway-env/highway_env/envs/u_turn_env.py

import numpy as np
from typing import Tuple
from gym.envs.registration import register


from highway_env import utils
from highway_env.envs.common.abstract import AbstractEnv
from highway_env.road.lane import LineType, StraightLane, CircularLane
from highway_env.road.road import Road, RoadNetwork
from highway_env.vehicle.controller import MDPVehicle


class UTurnEnv(AbstractEnv):

    """
    U-Turn risk analysis task: the agent overtakes vechiles that are blocking the
    traffic. High speed overtaking must be balanced with ensuring safety.
    """

    """Penalization received for vechile collision."""
    COLLISION_REWARD: float = -1.0
    """Reward received for maintaining left most lane."""
    LEFT_LANE_REWARD: float = 0.1
    """Reward received for maintaining cruising speed."""
    HIGH_SPEED_REWARD: float = 0.4
    """Reward received for maintaining course on road."""
    ON_ROAD_CONSTRAINT: float = 0.2

    @classmethod
    def default_config(cls) -> dict:
        config = super().default_config()
        config.update({
            "observation": {
                "type": "TimeToCollision",
                "horizon": 16
            },
            "action": {
                "type": "DiscreteMetaAction",
            },
            "screen_height": 789,  
            "screen_height": 289,
            "duration": 8,
            "reward_speed_range": [16, 24],
            "offroad_terminal": False
        })
        return config

    def _reward(self, action: int) -> float:
        """
        The vehicle is rewarded for driving with high speed and collision avoidance.
        :param action: the action performed
        :return: the reward of the state-action transition
        """
        neighbours = self.road.network.all_side_lanes(self.vehicle.lane_index)
        lane = self.vehicle.lane_index[2]
        scaled_speed = utils.lmap(self.vehicle.speed, self.config["reward_speed_range"], [0, 1])
        reward = \
            + self.COLLISION_REWARD * self.vehicle.crashed \
            + self.LEFT_LANE_REWARD * lane / max(len(neighbours) - 1, 1) \
            + self.HIGH_SPEED_REWARD * np.clip(scaled_speed, 0, 1) \
            + self.ON_ROAD_CONSTRAINT * self.vehicle.on_road
        reward = utils.lmap(reward,
                          [self.COLLISION_REWARD, self.HIGH_SPEED_REWARD + self.LEFT_LANE_REWARD],
                          [0, 1])
        reward = 0 if not self.vehicle.on_road else reward
        return reward

    def _is_terminal(self) -> bool:
        """
        The episode is over if the ego vehicle crashed or the time is out.
        """
        return self.vehicle.crashed or \
            self.steps >= self.config["duration"] # or \
            # (self.config["offroad_terminal"] and not self.vehicle.on_road)

    def _cost(self, action: int) -> float:
        """
        The constraint signal is the time spent driving on the opposite lane
        and occurrence of collisions.
        """
        return float(self.vehicle.crashed) \
               + float(self.vehicle.lane_index[2] == 0)/15

    def _reset(self) -> np.ndarray:
        self._make_road()
        self._make_vehicles()

    def _make_road(self, length=128):
        """
        Making double lane road with counter-clockwise U-Turn.
        :return: the road
        """
        net = RoadNetwork()

        # Defining upper starting lanes after the U-Turn.
        # These Lanes are defined from x-coordinate 'length' to 0.
        net.add_lane("c", "d", StraightLane([length, 0], [0, 0],
                                            line_types=(LineType.NONE, LineType.CONTINUOUS_LINE)))
        net.add_lane("c", "d", StraightLane([length, StraightLane.DEFAULT_WIDTH], [0, StraightLane.DEFAULT_WIDTH],
                                            line_types=(LineType.CONTINUOUS_LINE, LineType.STRIPED)))

        # Defining counter-clockwise circular U-Turn lanes.
        center = [length, StraightLane.DEFAULT_WIDTH + 20]  # [m]
        radius = 20  # [m]
        alpha = 0 # 24  # [deg]

        radii = [radius, radius+StraightLane.DEFAULT_WIDTH]
        n, c, s = LineType.NONE, LineType.CONTINUOUS, LineType.STRIPED
        line = [[c, s], [n, c]]
        for lane in [0, 1]:
            net.add_lane("b", "c",
                         CircularLane(center, radii[lane], np.deg2rad(90 - alpha), np.deg2rad(-90+alpha),
                                      clockwise=False, line_types=line[lane]))

        offset = 2*radius

        # Defining lower starting lanes before the U-Turn.
        # These Lanes are defined from x-coordinate 0 to 'length'.
        net.add_lane("a", "b", StraightLane([0, (2 * StraightLane.DEFAULT_WIDTH + offset)],
                                            [length, (2 * StraightLane.DEFAULT_WIDTH + offset)],
                                            line_types=(LineType.NONE,
                                                        LineType.CONTINUOUS_LINE)))
        net.add_lane("a", "b", StraightLane([0, ((2 * StraightLane.DEFAULT_WIDTH + offset) - StraightLane.DEFAULT_WIDTH)],
                                            [length, ((2 * StraightLane.DEFAULT_WIDTH + offset) - StraightLane.DEFAULT_WIDTH)],
                                            line_types=(LineType.CONTINUOUS_LINE,
                                                        LineType.STRIPED)))

        road = Road(network=net, np_random=self.np_random, record_history=self.config["show_trajectories"])
        self.road = road


    def _make_vehicles(self) -> None:
        """
        Strategic addition of vechiles for testing safety behavior limits
        while performing U-Turn manoeuvre at given cruising interval.

        :return: the ego-vehicle
        """

        # These variables add small variations to the driving behavior.
        position_deviation = 2
        speed_deviation = 2

        road = self.road
        ego_lane = self.road.network.get_lane(("a", "b", 1))
        ego_vehicle = self.action_type.vehicle_class(self.road,
                                                     ego_lane.position(0, 0),
                                                     speed=16)
        try:
            ego_vehicle.plan_route_to("d")
        except AttributeError:
            pass

        self.road.vehicles.append(ego_vehicle)
        self.vehicle = ego_vehicle
        

        vehicles_type = utils.class_from_path(self.config["other_vehicles_type"])

        # Note: randomize_behavior() can be commented out if more randomized
        # vechile interactions are deemed necessary for the experimentation.

        # Vechile 1: Blocking the ego vechile
        vehicle = vehicles_type.make_on_lane(self.road,
                                                   ("a", "b", 1),
                                                   longitudinal=25 + self.np_random.randn()*position_deviation,
                                                   speed=13.5 + self.np_random.randn() * speed_deviation)
        vehicle.plan_route_to('d')
        # vehicle.randomize_behavior()
        self.road.vehicles.append(vehicle)

        # Vechile 2: Forcing risky overtake
        vehicle = vehicles_type.make_on_lane(self.road,
                                                   ("a", "b", 0),
                                                   longitudinal=56 + self.np_random.randn()*position_deviation,
                                                   speed=14.5 + self.np_random.randn() * speed_deviation)
        vehicle.plan_route_to('d')
        # vehicle.randomize_behavior()
        self.road.vehicles.append(vehicle)

        # Vechile 3: Blocking the ego vechile
        vehicle = vehicles_type.make_on_lane(self.road,
                                                   ("b", "c", 1),
                                                   longitudinal=0.5 + self.np_random.randn()*position_deviation,
                                                   speed=4.5 + self.np_random.randn() * speed_deviation)
        vehicle.plan_route_to('d')
        # vehicle.randomize_behavior()
        self.road.vehicles.append(vehicle)

        # Vechile 4: Forcing risky overtake
        vehicle = vehicles_type.make_on_lane(self.road,
                                                   ("b", "c", 0),
                                                   longitudinal=17.5 + self.np_random.randn()*position_deviation,
                                                   speed=5.5 + self.np_random.randn() * speed_deviation)
        vehicle.plan_route_to('d')
        # vehicle.randomize_behavior()
        self.road.vehicles.append(vehicle)

        # Vechile 5: Blocking the ego vechile
        vehicle = vehicles_type.make_on_lane(self.road,
                                                   ("c", "d", 1),
                                                   longitudinal=1 + self.np_random.randn()*position_deviation,
                                                   speed=3.5 + self.np_random.randn() * speed_deviation)
        vehicle.plan_route_to('d')
        # vehicle.randomize_behavior()
        self.road.vehicles.append(vehicle)

        # Vechile 6: Forcing risky overtake
        vehicle = vehicles_type.make_on_lane(self.road,
                                                   ("c", "d", 0),
                                                   longitudinal=30 + self.np_random.randn()*position_deviation,
                                                   speed=5.5 + self.np_random.randn() * speed_deviation)
        vehicle.plan_route_to('d')
        # vehicle.randomize_behavior()
        self.road.vehicles.append(vehicle)


register(
    id='u-turn-v0',
    entry_point='highway_env.envs:UTurnEnv'
)