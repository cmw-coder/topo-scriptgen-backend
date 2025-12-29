import xml.etree.ElementTree as ET
from pathlib import Path
import logging
import shutil
import os
from typing import Optional

from app.core.path_manager import path_manager
from app.models.topox import Network, Device, Link, TopoxRequest, TopoxResponse
from app.utils.user_context import user_context

logger = logging.getLogger(__name__)


class TopoService:
    """拓扑服务，处理topox文件的保存和转换

    AI_FingerPrint_UUID: 20251225-LWJLVNvB
    """

    def __init__(self):
        self.path_manager = path_manager

    def _indent(self, elem: ET.Element, level: int = 0) -> None:
        """美化XML格式，进行缩进处理"""
        indent_str = "  "
        i = "\n" + level * indent_str
        if len(elem):
            if not elem.text or not elem.text.strip():
                elem.text = i + indent_str
            for child in elem:
                self._indent(child, level + 1)
            if not elem.tail or not elem.tail.strip():
                elem.tail = i
        else:
            if level and (not elem.tail or not elem.tail.strip()):
                elem.tail = i

    def build_topox_xml(self, request: TopoxRequest) -> str:
        """将请求转换为topox XML字符串"""
        try:
            network_elem = ET.Element("NETWORK")

            network = request.network
            device_list = network.device_list or []
            link_list = network.link_list or []

            # 添加设备列表
            device_list_elem = ET.SubElement(network_elem, "DEVICE_LIST")
            for device in device_list:
                device_elem = ET.SubElement(device_list_elem, "DEVICE")
                prop_elem = ET.SubElement(device_elem, "PROPERTY")
                ET.SubElement(prop_elem, "NAME").text = device.name or ""
                ET.SubElement(prop_elem, "TYPE").text = "Simware9"
                ET.SubElement(prop_elem, "ENABLE").text = "TRUE"
                ET.SubElement(prop_elem, "IS_DOUBLE_MCU").text = "FALSE"
                ET.SubElement(prop_elem, "IS_SINGLE_MCU").text = "FALSE"
                ET.SubElement(prop_elem, "IS_SAME_DUT_TYPE").text = "FALSE"
                ET.SubElement(prop_elem, "MAP_PRIORITY").text = "0"
                ET.SubElement(prop_elem, "IS_DUT").text = "true"
                ET.SubElement(prop_elem, "LOCATION").text = device.location or ""

            # 添加链路列表
            link_list_elem = ET.SubElement(network_elem, "LINK_LIST")
            for link in link_list:
                link_elem = ET.SubElement(link_list_elem, "LINK")
                start_device = link.start_device or ""
                end_device = link.end_device or ""
                start_port = link.start_port or ""
                end_port = link.end_port or ""

                for device_name, port_name in (
                    (start_device, start_port),
                    (end_device, end_port),
                ):
                    node_elem = ET.SubElement(link_elem, "NODE")
                    ET.SubElement(node_elem, "DEVICE").text = device_name
                    port_elem = ET.SubElement(node_elem, "PORT")
                    ET.SubElement(port_elem, "NAME").text = port_name
                    ET.SubElement(port_elem, "TYPE").text = ""
                    ET.SubElement(port_elem, "IPAddr").text = ""
                    ET.SubElement(port_elem, "IPv6Addr").text = ""
                    ET.SubElement(port_elem, "SLOT_TYPE").text = ""
                    ET.SubElement(port_elem, "TAG").text = ""

            self._indent(network_elem)
            xml_bytes = ET.tostring(
                network_elem, encoding="utf-8", xml_declaration=True
            )
            return xml_bytes.decode("utf-8")

        except Exception as e:
            logger.error(f"构建topox XML失败: {str(e)}")
            raise

    def parse_topox_xml(self, xml_text: str) -> Network:
        """解析topox XML为Network对象"""
        try:
            network = Network(device_list=[], link_list=[])

            if not xml_text.strip():
                logger.warning("XML内容为空，返回空的Network对象")
                return network

            root = ET.fromstring(xml_text)

            # 解析设备列表
            device_list_elem = root.find("DEVICE_LIST")
            if device_list_elem is not None:
                for device_elem in device_list_elem.findall("DEVICE"):
                    prop_elem = device_elem.find("PROPERTY")
                    device_name = ""
                    device_location = ""
                    if prop_elem is not None:
                        name_elem = prop_elem.find("NAME")
                        location_elem = prop_elem.find("LOCATION")
                        device_name = name_elem.text if name_elem is not None else ""
                        device_location = (
                            location_elem.text if location_elem is not None else ""
                        )

                    if device_name:  # 只添加有名称的设备
                        network.device_list.append(
                            Device(name=device_name, location=device_location)
                        )

            # 解析链路列表
            link_list_elem = root.find("LINK_LIST")
            if link_list_elem is not None:
                for link_elem in link_list_elem.findall("LINK"):
                    nodes = link_elem.findall("NODE")
                    if len(nodes) < 2:
                        continue

                    def _node_details(node: ET.Element) -> tuple[str, str]:
                        device_elem = node.find("DEVICE")
                        port_name_elem = node.find("PORT/NAME")
                        device_name = (
                            device_elem.text if device_elem is not None else ""
                        )
                        port_name = (
                            port_name_elem.text if port_name_elem is not None else ""
                        )
                        return device_name or "", port_name or ""

                    start_device, start_port = _node_details(nodes[0])
                    end_device, end_port = _node_details(nodes[1])

                    # 只添加有效的链路
                    if start_device and end_device:
                        network.link_list.append(
                            Link(
                                start_device=start_device,
                                start_port=start_port,
                                end_device=end_device,
                                end_port=end_port,
                            )
                        )

            return network

        except ET.ParseError as e:
            logger.error(f"解析topox XML失败: {str(e)}")
            raise ValueError(f"XML解析错误: {str(e)}")
        except Exception as e:
            logger.error(f"解析topox XML时发生未知错误: {str(e)}")
            raise

    async def save_topox(
        self, request: TopoxRequest, filename: str = "default.topox"
    ) -> TopoxResponse:
        """保存topox文件"""
        try:
            # 构建XML内容
            xml_content = self.build_topox_xml(request)

            # 获取topox目录
            topox_dir = self.path_manager.get_topox_dir()
            file_path = topox_dir / filename

            # 确保目录存在
            topox_dir.mkdir(parents=True, exist_ok=True)

            # 写入文件
            file_path.write_text(xml_content, encoding="utf-8")

            logger.info(f"成功保存topox文件: {file_path}")

            # 自动复制到 AIGC 目标目录
            try:
                self._copy_to_aigc_target(file_path, filename)
            except Exception as copy_error:
                # 复制失败不影响主流程，只记录错误
                logger.warning(f"复制topox文件到AIGC目标目录失败: {str(copy_error)}")

            return TopoxResponse(
                network=request.network,
                xml_content=xml_content,
                file_path=str(file_path),
            )

        except Exception as e:
            logger.error(f"保存topox文件失败: {str(e)}")
            raise

    async def load_topox(self, filename: str = "default.topox") -> TopoxResponse:
        """加载topox文件"""
        try:
            # 获取topox目录
            topox_dir = self.path_manager.get_topox_dir()
            file_path = topox_dir / filename

            if not file_path.exists():
                logger.warning(f"topox文件不存在: {file_path}，返回空网络")
                return TopoxResponse(
                    network=Network(device_list=[], link_list=[]),
                    xml_content=None,
                    file_path=str(file_path),
                )

            # 读取文件内容
            xml_content = file_path.read_text(encoding="utf-8")

            # 解析XML
            network = self.parse_topox_xml(xml_content)

            logger.info(f"成功加载topox文件: {file_path}")

            return TopoxResponse(
                network=network, xml_content=xml_content, file_path=str(file_path)
            )

        except ET.ParseError as e:
            logger.error(f"topox文件XML格式错误: {file_path}, 错误: {str(e)}")
            raise ValueError(f"topox文件格式错误: {str(e)}")
        except Exception as e:
            logger.error(f"加载topox文件失败: {str(e)}")
            raise

    async def delete_topox(self, filename: str) -> bool:
        """删除topox文件"""
        try:
            # 获取topox目录
            topox_dir = self.path_manager.get_topox_dir()
            file_path = topox_dir / filename

            if not file_path.exists():
                logger.warning(f"topox文件不存在: {file_path}")
                return False

            file_path.unlink()
            logger.info(f"成功删除topox文件: {file_path}")
            return True

        except Exception as e:
            logger.error(f"删除topox文件失败: {str(e)}")
            return False

    async def list_topox_files(self) -> list[str]:
        """列出所有topox文件"""
        try:
            # 获取topox目录
            topox_dir = self.path_manager.get_topox_dir()
            if not topox_dir.exists():
                return []

            # 列出所有.topox文件
            topox_files = [f.name for f in topox_dir.glob("*.topox") if f.is_file()]

            return sorted(topox_files)

        except Exception as e:
            logger.error(f"列出topox文件失败: {str(e)}")
            return []

    def _copy_to_aigc_target(self, source_file_path: Path, filename: str) -> None:
        """
        按照 aigc_tool.py 中的逻辑复制文件到目标目录

        Args:
            source_file_path: 源文件路径
            filename: 文件名
        """
        try:
            # 获取用户名和目标目录
            username = user_context.get_username()
            target_dir = user_context.get_aigc_target_dir()

            # 确保目标目录存在
            os.makedirs(target_dir, exist_ok=True)

            # 确定目标文件路径
            target_path = os.path.join(target_dir, filename)

            # 如果目标文件已存在，尝试删除它（处理权限问题）
            if os.path.exists(target_path):
                try:
                    os.remove(target_path)
                    logger.debug(f"已删除旧的目标文件: {target_path}")
                except PermissionError:
                    # 如果无法删除，尝试使用不同的方式
                    logger.warning(f"无法删除旧文件 {target_path}，将尝试其他方式")

            # 复制文件
            shutil.copy2(source_file_path, target_path)

            # 递归设置 777 权限
            user_context.set_permissions_recursive(target_dir, 0o777)

            logger.info(f"成功复制 topox 文件到 AIGC 目标目录: {target_path}")

        except Exception as e:
            logger.error(f"复制文件到 AIGC 目标目录失败: {str(e)}")
            raise


# 创建topo服务实例
topo_service = TopoService()
