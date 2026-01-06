from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

import httpx
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

from app.models.topox import TopoxRequest
from app.services.topo_service import topo_service

logger = logging.getLogger(__name__)
router = APIRouter()

GNS3_BASE_URL = "https://gns3-server.coder-open.h3c.com"
GNS3_TIMEOUT = 30  # seconds


def load_project_id_from_file() -> tuple[str, str | None]:
    """Load project id from ~/.gns3_project_id with logging."""
    project_id_path = Path.home() / ".gns3_project_id"
    try:
        project_id = project_id_path.read_text(encoding="utf-8").strip()
    except OSError:
        logger.exception("Failed to read %s", project_id_path)
        return "", "Failed to read project id file."

    if not project_id:
        logger.error("%s is empty", project_id_path)
        return "", "Project id file is empty."

    return project_id, None


async def get_gns3_token() -> tuple[str, JSONResponse | None]:
    """Authenticate to GNS3 and return an access token or an error response."""
    auth_url = f"{GNS3_BASE_URL.rstrip('/')}/v3/access/users/authenticate"
    try:
        async with httpx.AsyncClient(
            verify=False,
            trust_env=False,
            timeout=httpx.Timeout(GNS3_TIMEOUT),
        ) as client:
            auth_resp = await client.post(
                auth_url, json={"username": "admin", "password": "admin"}
            )
    except httpx.HTTPError:
        logger.exception("Failed to authenticate with GNS3")
        return "", JSONResponse(
            content={"status": "error", "message": "Failed to reach GNS3 server."},
            status_code=502,
        )

    if auth_resp.status_code not in (200, 201):
        logger.error("GNS3 auth failed status:%s", auth_resp.status_code)
        return "", JSONResponse(
            content={"status": "error", "message": "GNS3 authentication failed."},
            status_code=502,
        )

    try:
        token = auth_resp.json().get("access_token", "")
    except ValueError:
        logger.exception("Failed to decode GNS3 auth response")
        return "", JSONResponse(
            content={"status": "error", "message": "Invalid response from GNS3."},
            status_code=502,
        )

    if not token:
        logger.error("GNS3 auth response missing access_token")
        return "", JSONResponse(
            content={"status": "error", "message": "No access_token received from GNS3."},
            status_code=502,
        )

    return token, None


@router.post("/topox-from-gns3")
async def post_topox_from_gns3(request: Request) -> JSONResponse:
    token, token_error = await get_gns3_token()
    if token_error:
        return token_error

    try:
        payload_raw: Any = await request.json()
    except (json.JSONDecodeError, ValueError):
        logger.warning("POST /api/v1/topox-from-gns3 received no JSON body or invalid JSON")
        payload_raw = {}
    except Exception:
        logger.exception("POST /api/v1/topox-from-gns3 failed to parse JSON body")
        payload_raw = {}

    payload: Dict[str, Any] = payload_raw if isinstance(payload_raw, dict) else {}
    logger.info(
        "POST /api/v1/topox-from-gns3 payload: %s", json.dumps(payload, ensure_ascii=False)
    )

    project_id = payload.get("project_id") if isinstance(payload.get("project_id"), str) else ""
    project_id_error: str | None = None
    if not project_id:
        project_id, project_id_error = load_project_id_from_file()

    if not project_id:
        return JSONResponse(
            content={
                "status": "error",
                "message": project_id_error or "project_id is required (body or .gns3_project_id).",
            },
            status_code=400,
        )

    nodes_url = f"{GNS3_BASE_URL}/v3/projects/{project_id}/nodes"
    links_url = f"{GNS3_BASE_URL}/v3/projects/{project_id}/links"
    auth_headers = {"Authorization": f"Bearer {token}"}

    try:
        async with httpx.AsyncClient(
            verify=False,
            trust_env=False,
            timeout=httpx.Timeout(GNS3_TIMEOUT),
        ) as client:
            nodes_resp, links_resp = await client.get(
                nodes_url, headers=auth_headers
            ), await client.get(links_url, headers=auth_headers)
    except httpx.HTTPError:
        logger.exception("Failed to fetch topology data from GNS3")
        return JSONResponse(
            content={"status": "error", "message": "Failed to reach GNS3 server."},
            status_code=502,
        )

    if nodes_resp.status_code != 200 or links_resp.status_code != 200:
        logger.error(
            "GNS3 API error nodes:%s links:%s", nodes_resp.status_code, links_resp.status_code
        )
        return JSONResponse(
            content={"status": "error", "message": "GNS3 API returned an error."},
            status_code=502,
        )

    try:
        nodes_data: List[Dict[str, Any]] = nodes_resp.json()  # type: ignore[assignment]
        links_data: List[Dict[str, Any]] = links_resp.json()  # type: ignore[assignment]
    except ValueError:
        logger.exception("Failed to decode GNS3 responses")
        return JSONResponse(
            content={"status": "error", "message": "Invalid response from GNS3."},
            status_code=502,
        )

    if not isinstance(nodes_data, list):
        nodes_data = []
    if not isinstance(links_data, list):
        links_data = []

    node_id_to_name: Dict[str, str] = {}
    node_id_to_portmap: Dict[str, Dict[str, str]] = {}
    device_list: List[Dict[str, str]] = []

    for node in nodes_data or []:
        if not isinstance(node, dict):
            continue
        name = str(node.get("name", ""))
        node_id = str(node.get("node_id", ""))
        x = node.get("x")
        y = node.get("y")
        location = f"{x},{y}" if x is not None and y is not None else ""
        device_list.append({"name": name, "location": location})
        if node_id:
            node_id_to_name[node_id] = name

        properties = node.get("properties") if isinstance(node, dict) else None
        ports_mapping = properties.get("ports_mapping") if isinstance(properties, dict) else None
        if ports_mapping is None:
            ports_mapping = properties.get("ports") if isinstance(properties, dict) else None
        if isinstance(ports_mapping, list):
            port_map: Dict[str, str] = {}
            for port in ports_mapping:
                if not isinstance(port, dict):
                    continue
                port_num = port.get("port_number")
                if port_num is None:
                    continue
                iface = port.get("interface") or port.get("name") or ""
                port_map[str(port_num)] = str(iface)
            if port_map and node_id:
                node_id_to_portmap[node_id] = port_map

    link_list: List[Dict[str, str]] = []
    for link in links_data or []:
        if not isinstance(link, dict):
            continue
        link_nodes = link.get("nodes") or []
        if not isinstance(link_nodes, list) or len(link_nodes) < 2:
            continue

        start_node = link_nodes[0] if isinstance(link_nodes[0], dict) else {}
        end_node = link_nodes[1] if isinstance(link_nodes[1], dict) else {}

        start_node_id = str(start_node.get("node_id", ""))
        end_node_id = str(end_node.get("node_id", ""))

        start_device = node_id_to_name.get(start_node_id, "")
        end_device = node_id_to_name.get(end_node_id, "")

        start_port_number = start_node.get("port_number")
        end_port_number = end_node.get("port_number")

        start_port = node_id_to_portmap.get(start_node_id, {}).get(
            str(start_port_number), str(start_port_number or "")
        )
        end_port = node_id_to_portmap.get(end_node_id, {}).get(
            str(end_port_number), str(end_port_number or "")
        )

        link_list.append(
            {
                "start_device": start_device,
                "start_port": start_port,
                "end_device": end_device,
                "end_port": end_port,
            }
        )

    network = {"device_list": device_list, "link_list": link_list}
    # Convert dict to TopoxRequest and use service layer builder
    topox_request = TopoxRequest.model_validate({"network": network})
    topox_xml = topo_service.build_topox_xml(topox_request)

    topox_path = Path.home() / "project" / "default.topox"
    try:
        topox_path.parent.mkdir(parents=True, exist_ok=True)
        topox_path.write_text(topox_xml, encoding="utf-8")
        logger.info("Wrote topox to %s", topox_path)
        return JSONResponse(content={"status": "ok", "data": topox_xml}, status_code=200)
    except OSError:
        logger.exception("Failed to write topox to %s", topox_path)
        return JSONResponse(
            content={"status": "error", "message": "Failed to write topox file."},
            status_code=500,
        )


@router.get("/to-web-ui", response_model=None)
async def to_web_ui() -> Response:
    logger.info("GET /to-web-ui")
    token, token_error = await get_gns3_token()
    if token_error:
        return token_error

    project_id, project_id_error = load_project_id_from_file()
    if project_id_error:
        return JSONResponse(
            content={"status": "error", "message": project_id_error},
            status_code=500,
        )

    target_url = (
        f"{GNS3_BASE_URL.rstrip('/')}/static/web-ui/controller/1/project/"
        f"{project_id}?token={token}"
    )
    return RedirectResponse(url=target_url, status_code=302)

