from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from .obsws import ObsClient, ObsError


DEFAULT_YOUTUBE_RTMP_URL = "rtmp://a.rtmp.youtube.com/live2"


@dataclass(frozen=True)
class SourceSpec:
    name: str
    url: str
    scene: str


@dataclass(frozen=True)
class StreamLayout:
    observer_scene: str = "Actuallyabot - Observer"
    player_scene: str = "Actuallyabot - Player"
    opponent_scene: str = "Actuallyabot - Opponent"
    width: int = 1280
    height: int = 720

    @classmethod
    def from_env(cls) -> "StreamLayout":
        return cls(
            observer_scene=os.environ.get("STREAMBOT_OBSERVER_SCENE", cls.observer_scene),
            player_scene=os.environ.get("STREAMBOT_PLAYER_SCENE", cls.player_scene),
            opponent_scene=os.environ.get("STREAMBOT_OPPONENT_SCENE", cls.opponent_scene),
            width=int(os.environ.get("STREAMBOT_CANVAS_WIDTH", "1280")),
            height=int(os.environ.get("STREAMBOT_CANVAS_HEIGHT", "720")),
        )


class StreamController:
    def __init__(self, obs: ObsClient, layout: StreamLayout | None = None) -> None:
        self.obs = obs
        self.layout = layout or StreamLayout.from_env()

    def configure_stream_service(self, stream_key: str, server: str = DEFAULT_YOUTUBE_RTMP_URL) -> None:
        self.obs.call(
            "SetStreamServiceSettings",
            {
                "streamServiceType": "rtmp_custom",
                "streamServiceSettings": {
                    "server": server,
                    "key": stream_key,
                    "use_auth": False,
                },
            },
        )

    def ensure_layout(
        self,
        *,
        player_live_view_url: str,
        opponent_live_view_url: str | None = None,
        observer_url: str | None = None,
    ) -> None:
        self._ensure_scene(self.layout.observer_scene)
        self._ensure_scene(self.layout.player_scene)
        self._ensure_scene(self.layout.opponent_scene)

        player = SourceSpec("CUA Player Live View", player_live_view_url, self.layout.player_scene)
        self._ensure_browser_source(player)

        if opponent_live_view_url:
            opponent = SourceSpec("Opponent Live View", opponent_live_view_url, self.layout.opponent_scene)
            self._ensure_browser_source(opponent)

        observer_target = observer_url or player_live_view_url
        observer = SourceSpec("Observer Live View", observer_target, self.layout.observer_scene)
        self._ensure_browser_source(observer)

        self.switch_scene(self.layout.observer_scene)

    def start_streaming(self) -> None:
        status = self.obs.call("GetStreamStatus")
        if status.get("outputActive"):
            return
        self.obs.call("StartStream")

    def stop_streaming(self) -> None:
        status = self.obs.call("GetStreamStatus")
        if not status.get("outputActive"):
            return
        self.obs.call("StopStream")

    def switch_scene(self, scene_name: str) -> None:
        self.obs.call("SetCurrentProgramScene", {"sceneName": scene_name})

    def handle_event(self, event: dict[str, Any]) -> str:
        event_type = event.get("type")
        payload = event.get("payload") or {}
        if event_type == "turn_start":
            scene = self.layout.player_scene
        elif event_type == "turn_end":
            scene = self.layout.observer_scene
        elif event_type == "game_over":
            scene = self.layout.observer_scene
        elif event_type == "scene":
            scene = str(payload.get("scene") or self.layout.observer_scene)
        else:
            scene = self.layout.observer_scene
        self.switch_scene(scene)
        return scene

    def _ensure_scene(self, scene_name: str) -> None:
        scenes = self.obs.call("GetSceneList").get("scenes", [])
        if any(scene.get("sceneName") == scene_name for scene in scenes):
            return
        self.obs.call("CreateScene", {"sceneName": scene_name})

    def _ensure_browser_source(self, spec: SourceSpec) -> None:
        created = False
        existing = self.obs.try_call("GetInputSettings", {"inputName": spec.name})
        settings = {
            "url": spec.url,
            "width": self.layout.width,
            "height": self.layout.height,
            "css": "body { margin: 0; overflow: hidden; background: #000; }",
            "reroute_audio": False,
        }
        if existing is None:
            self.obs.call(
                "CreateInput",
                {
                    "sceneName": spec.scene,
                    "inputName": spec.name,
                    "inputKind": "browser_source",
                    "inputSettings": settings,
                    "sceneItemEnabled": True,
                },
            )
            created = True
        else:
            self.obs.call(
                "SetInputSettings",
                {
                    "inputName": spec.name,
                    "inputSettings": settings,
                    "overlay": True,
                },
            )

        item_id = self._ensure_scene_item(spec.scene, spec.name, created=created)
        self.obs.call(
            "SetSceneItemTransform",
            {
                "sceneName": spec.scene,
                "sceneItemId": item_id,
                "sceneItemTransform": {
                    "positionX": 0,
                    "positionY": 0,
                    "scaleX": 1,
                    "scaleY": 1,
                    "boundsType": "OBS_BOUNDS_STRETCH",
                    "boundsWidth": self.layout.width,
                    "boundsHeight": self.layout.height,
                },
            },
        )

    def _ensure_scene_item(self, scene: str, source: str, *, created: bool) -> int:
        item = self.obs.try_call("GetSceneItemId", {"sceneName": scene, "sourceName": source})
        if item and "sceneItemId" in item:
            return int(item["sceneItemId"])
        if created:
            raise ObsError(f"OBS created input {source!r} but did not attach it to {scene!r}")
        self.obs.call("CreateSceneItem", {"sceneName": scene, "sourceName": source})
        item = self.obs.call("GetSceneItemId", {"sceneName": scene, "sourceName": source})
        return int(item["sceneItemId"])

