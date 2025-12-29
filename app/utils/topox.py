from logging import getLogger
from typing import Optional
from xml.etree.ElementTree import Element, SubElement, tostring, fromstring, ParseError

from app.models.topox import Network, TopoxRequest, Device, Link

logger = getLogger(__name__)


def _auto_indent(elem: Element, level: int = 0) -> None:
    """Pretty-print XML by indenting in-place."""

    indent_str = "  "
    i = "\n" + level * indent_str
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + indent_str
        for child in elem:
            _auto_indent(child, level + 1)
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = i


def build_topox(payload: TopoxRequest) -> str:
    """Convert request payload to topox XML string."""

    network_elem = Element("NETWORK")
    device_list_elem = SubElement(network_elem, "DEVICE_LIST")
    link_list_elem = SubElement(network_elem, "LINK_LIST")

    network_section: Optional[Network] = payload.get("network")
    if network_section is not None and isinstance(network_section, Network):
        device_list = network_section.get("device_list")
        if device_list is not None:
            for device in device_list:
                device_elem = SubElement(device_list_elem, "DEVICE")
                prop_elem = SubElement(device_elem, "PROPERTY")
                SubElement(prop_elem, "NAME").text = device.get("name", "")
                SubElement(prop_elem, "TYPE").text = "Simware9"
                SubElement(prop_elem, "ENABLE").text = "TRUE"
                SubElement(prop_elem, "IS_DOUBLE_MCU").text = "FALSE"
                SubElement(prop_elem, "IS_SINGLE_MCU").text = "FALSE"
                SubElement(prop_elem, "IS_SAME_DUT_TYPE").text = "FALSE"
                SubElement(prop_elem, "MAP_PRIORITY").text = "0"
                SubElement(prop_elem, "IS_DUT").text = "true"
                SubElement(prop_elem, "LOCATION").text = device.get("location", "")
        link_list = network_section.get("link_list")
        if link_list is not None:
            for link in link_list:
                link_elem = SubElement(link_list_elem, "LINK")
                start_device = link.get("start_device", "")
                end_device = link.get("end_device", "")
                start_port = link.get("start_port", "")
                end_port = link.get("end_port", "")
                for device_name, port_name in (
                    (start_device, start_port),
                    (end_device, end_port),
                ):
                    node_elem = SubElement(link_elem, "NODE")
                    SubElement(node_elem, "DEVICE").text = device_name
                    port_elem = SubElement(node_elem, "PORT")
                    SubElement(port_elem, "NAME").text = port_name
                    SubElement(port_elem, "TYPE").text = ""
                    SubElement(port_elem, "IPAddr").text = ""
                    SubElement(port_elem, "IPv6Addr").text = ""
                    SubElement(port_elem, "SLOT_TYPE").text = ""
                    SubElement(port_elem, "TAG").text = ""

    # _auto_indent(network_elem)
    xml_bytes = tostring(network_elem, encoding="utf-8", xml_declaration=True)
    return xml_bytes.decode("utf-8")


def parse_topox(xml_text: str) -> Network:
    """Parse topox XML into Network dict."""

    network = Network(device_list=[], link_list=[])

    try:
        root = fromstring(xml_text)
    except ParseError:
        logger.exception("Failed to parse topox XML")
        raise

    device_list_elem = root.find("DEVICE_LIST")
    if device_list_elem is not None:
        for raw_device_elem in device_list_elem.findall("DEVICE"):
            prop_elem = raw_device_elem.find("PROPERTY")
            raw_device_name = ""
            raw_device_location = ""
            if prop_elem is not None:
                name_elem = prop_elem.find("NAME")
                location_elem = prop_elem.find("LOCATION")
                raw_device_name = name_elem.text if name_elem is not None else ""
                raw_device_location = (
                    location_elem.text if location_elem is not None else ""
                )
            network.device_list.append(
                Device(name=raw_device_name or "", location=raw_device_location or "")
            )

    link_list_elem = root.find("LINK_LIST")
    if link_list_elem is not None:
        for link_elem in link_list_elem.findall("LINK"):
            nodes = link_elem.findall("NODE")
            if len(nodes) < 2:
                continue

            def _node_details(node: Element) -> tuple[str, str]:
                device_elem = node.find("DEVICE")
                port_name_elem = node.find("PORT/NAME")
                device_name = device_elem.text if device_elem is not None else ""
                port_name = port_name_elem.text if port_name_elem is not None else ""
                return device_name or "", port_name or ""

            start_device, start_port = _node_details(nodes[0])
            end_device, end_port = _node_details(nodes[1])

            network.link_list.append(
                Link(
                    start_device=start_device,
                    start_port=start_port,
                    end_device=end_device,
                    end_port=end_port,
                )
            )

    return network
