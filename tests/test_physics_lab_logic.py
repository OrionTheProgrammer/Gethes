from types import SimpleNamespace

from gethes.games.physics_lab import PhysicsLabGame


def test_scoring_pose_accepts_target_zone() -> None:
    assert PhysicsLabGame._is_scoring_pose(350.0, 28.0, 15.0)


def test_scoring_pose_rejects_outside_zone() -> None:
    assert not PhysicsLabGame._is_scoring_pose(300.0, 28.0, 15.0)
    assert not PhysicsLabGame._is_scoring_pose(350.0, 52.0, 15.0)
    assert not PhysicsLabGame._is_scoring_pose(350.0, 28.0, 140.0)


def test_world_to_grid_bounds() -> None:
    game = PhysicsLabGame(SimpleNamespace())
    assert game._to_grid(0.0, 0.0) == (0, 0)
    assert game._to_grid(game.world_w, game.world_h) == (game.grid_w - 1, game.grid_h - 1)
