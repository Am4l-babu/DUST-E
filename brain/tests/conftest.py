import pytest

from dustebrain.config import BrainConfig, load_config
from dustebrain.sim.scenario import Scenario
from dustebrain.vision.tracker import Tracker
from dustebrain.world.model import WorldModel


@pytest.fixture(scope="session")
def cfg() -> BrainConfig:
    return load_config()


def run_scenario(cfg: BrainConfig, scenario: Scenario):
    """Drive the production tracker + world model with a scripted scenario."""
    tracker = Tracker(cfg)
    world = WorldModel(cfg)
    events = []
    for frame in scenario.frames(cfg):
        tracks = tracker.update(frame.detections, frame.t)
        events.extend(world.update(tracks, frame.t, frame.ego_forward_mps))
    return world, events


def types_of(events, person_id=None):
    return [e.type.value for e in events if person_id is None or e.person_id == person_id]
