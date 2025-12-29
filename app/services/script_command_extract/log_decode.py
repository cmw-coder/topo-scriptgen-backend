import json
import re
import base64
from typing import Any, Dict, List, Optional
from pathlib import Path


class JSONProcessor:
    """JSON 文件处理器，用于解码 Base64 内容和处理特殊字符"""

    def __init__(self, input_file: str, output_file: Optional[str] = None):
        """
        初始化 JSON 处理器

        Args:
            input_file: 输入 JSON 文件路径
            output_file: 输出 JSON 文件路径（可选）
        """
        self.input_file = Path(input_file)
        self.output_file = Path(output_file) if output_file else None
        self.data = None
        self._encodings = ["utf-8", "gbk", "gb2312", "latin-1", "iso-8859-1"]

    def read_json_file(self) -> Any:
        """读取 JSON 文件"""
        if not self.input_file.exists():
            raise FileNotFoundError(f"文件不存在: {self.input_file}")

        with open(self.input_file, "r", encoding="utf-8") as file:
            self.data = json.load(file)
        return self.data

    def decode_base64_in_json(self, data: Optional[Any] = None) -> Any:
        """递归解码 JSON 中的 Base64 编码字段"""
        if data is None:
            if self.data is None:
                raise ValueError("没有可处理的数据，请先调用 read_json_file()")
            data = self.data

        if isinstance(data, dict):
            return self._process_dict_for_base64(data)
        elif isinstance(data, list):
            return self._process_list_for_base64(data)
        elif isinstance(data, str):
            return self._decode_base64_string(data)
        else:
            return data

    def _process_dict_for_base64(self, data: Dict) -> Dict:
        """处理字典中的 Base64 编码字段"""
        result = {}
        for key, value in data.items():
            result[key] = self.decode_base64_in_json(value)
        return result

    def _process_list_for_base64(self, data: List) -> List:
        """处理列表中的 Base64 编码字段"""
        return [self.decode_base64_in_json(item) for item in data]

    def _decode_base64_string(self, value: str) -> str:
        """解码单个 Base64 编码字符串"""
        # 匹配 _HTML:b'...' 格式（包含单引号）
        match1 = re.match(r"^_(HTML|CMD):b\'(.*?)\'$", value)
        if match1:
            b64_str = match1.group(2)
            return self._decode_base64_bytes(b64_str)
        return value

    def _decode_base64_bytes(self, b64_str: str) -> str:
        """解码 Base64 字节数据"""
        try:
            decoded_bytes = base64.b64decode(b64_str)

            # 尝试多种编码方式
            for encoding in self._encodings:
                try:
                    decoded_text = decoded_bytes.decode(encoding)
                    print(
                        f"成功解码 Base64 (使用 {encoding}): {repr(decoded_text[:50])}..."
                    )
                    return decoded_text
                except UnicodeDecodeError:
                    continue

            # 如果所有编码都失败，返回原始值
            print(f"解码失败，返回原始值: {b64_str[:30]}...")
            return f"_HTML:{b64_str}"

        except Exception as e:
            print(f"Base64 解码错误: {e}")
            return f"_HTML:{b64_str}"

    def replace_newlines(self, data: Optional[Any] = None) -> Any:
        """递归遍历对象，把字符串里的 '\n' 转成真实换行"""
        if data is None:
            if self.data is None:
                raise ValueError("没有可处理的数据，请先调用 read_json_file()")
            data = self.data

        if isinstance(data, dict):
            return self._process_dict_for_newlines(data)
        elif isinstance(data, list):
            return self._process_list_for_newlines(data)
        elif isinstance(data, str):
            return self._replace_escaped_newlines(data)
        else:
            return data

    def _process_dict_for_newlines(self, data: Dict) -> Dict:
        """处理字典中的换行符"""
        return {k: self.replace_newlines(v) for k, v in data.items()}

    def _process_list_for_newlines(self, data: List) -> List:
        """处理列表中的换行符"""
        return [self.replace_newlines(item) for item in data]

    def _replace_escaped_newlines(self, text: str) -> str:
        """替换字符串中的转义换行符"""
        return text.replace("\\n", "\n")

    def save_processed_json(self, output_path: Optional[str] = None) -> None:
        """保存处理后的数据到 JSON 文件"""
        if self.data is None:
            raise ValueError("没有可保存的数据，请先处理数据")

        if output_path:
            output_file = Path(output_path)
        elif self.output_file:
            output_file = self.output_file
        else:
            raise ValueError("未指定输出文件路径")

        with open(output_file, "w", encoding="utf-8") as file:
            json.dump(self.data, file, ensure_ascii=False, indent=2)

    def process(self) -> Any:
        """完整处理 JSON 文件的流程"""
        # 1. 读取 JSON 文件
        print(f"正在读取文件: {self.input_file}")
        self.read_json_file()

        # 2. 解码 Base64 内容
        print("正在解码 Base64 内容...")
        self.data = self.decode_base64_in_json()

        # 3. 替换换行符
        print("正在替换换行符...")
        self.data = self.replace_newlines()

        # 4. 保存结果（如果指定了输出文件）
        if self.output_file:
            self.save_processed_json()
            print(f"处理完成！结果已保存到: {self.output_file}")

        return self.data

    def get_data(self) -> Any:
        """获取处理后的数据"""
        return self.data

    def set_encodings(self, encodings: List[str]) -> None:
        """设置 Base64 解码时尝试的编码顺序"""
        self._encodings = encodings


# 使用示例
if __name__ == "__main__":
    try:
        # 方法1：使用类实例
        processor = JSONProcessor(
            input_file="/home/y28677/w31815/tmps/test_bjp.json",
            output_file="/home/y28677/w31815/tmps/processed_data.json",
        )
        processed_data = processor.process()

    except FileNotFoundError as e:
        print(f"错误: {e}")
    except json.JSONDecodeError as e:
        print(f"JSON 解析错误: {e}")
    except Exception as e:
        print(f"处理过程中发生错误: {e}")
