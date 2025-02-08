import os
import json
from astrbot.api.event import (
    filter,
    AstrMessageEvent,
    EventMessageType,
    permission_type,
    PermissionType
)
from astrbot.api.star import Context, Star, register

# 持久化配置文件路径，保存在插件所在目录下
CONFIG_FILE = os.path.join(os.path.dirname(__file__), "alias_config.json")

@register("alias", "Your Name", "支持批量执行一串命令的别名系统插件", "1.0.0", "repo url")
class AliasPlugin(Star):
    def __init__(self, context: Context, config: dict):
        """
        初始化插件时接收 Context 和配置字典。
        期望配置中有一个 "aliases" 键，格式为 {别名: 映射字符串}。
        同时尝试加载持久化文件中的数据，并合并更新当前别名字典。
        """
        super().__init__(context)
        self.aliases = config.get("aliases", {})  # 初始映射，如 {"greet": "helloworld"}
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf8") as f:
                    data = json.load(f)
                    # 以持久化文件中的数据为准，更新当前映射
                    self.aliases.update(data.get("aliases", {}))
            except Exception as e:
                self.logger.error(f"加载持久化配置失败: {e}")

    def _save_config(self):
        """
        将当前别名映射数据写入持久化配置文件。
        """
        try:
            with open(CONFIG_FILE, "w", encoding="utf8") as f:
                json.dump({"aliases": self.aliases}, f, ensure_ascii=False, indent=4)
        except Exception as e:
            self.logger.error(f"保存持久化配置失败: {e}")

    # -------------------------------
    # 命令组：别名管理（支持单个及批量映射）
    # -------------------------------
    @filter.command_group("alias")
    def alias_group(self):
        """别名管理命令组，提供添加、删除、列出及批量设置映射"""
        pass

    @alias_group.command("add")
    @permission_type(PermissionType.ADMIN)
    async def add_alias(self, event: AstrMessageEvent, name: str, mapping: str):
        """
        添加或更新单个别名映射。
        该映射支持单个命令，也可用分号分隔多个命令（批量执行）。
        
        用法: /alias add <name> <mapping>
        
        示例1: /alias add greet helloworld  
          当用户发送 "/greet" 时，将执行 "/helloworld"。
        
        示例2: /alias add combo "cmd1 arg; cmd2; cmd3"  
          当用户发送 "/combo extra_params" 时，将依次执行：
            /cmd1 arg extra_params
            /cmd2
            /cmd3
        """
        self.aliases[name] = mapping
        self._save_config()
        yield event.plain_result(f"已创建/更新别名 '{name}' -> '{mapping}'")

    @alias_group.command("remove")
    @permission_type(PermissionType.ADMIN)
    async def remove_alias(self, event: AstrMessageEvent, name: str):
        """
        删除指定别名映射。
        
        用法: /alias remove <name>
        """
        if name in self.aliases:
            del self.aliases[name]
            self._save_config()
            yield event.plain_result(f"已删除别名 '{name}'")
        else:
            yield event.plain_result(f"未找到别名 '{name}'")

    @alias_group.command("list")
    async def list_aliases(self, event: AstrMessageEvent):
        """
        列出所有已注册的别名映射及其对应的命令序列。
        
        用法: /alias list
        """
        if not self.aliases:
            yield event.plain_result("当前没有配置任何别名。")
        else:
            lines = ["当前别名映射列表:"]
            for key, mapping in self.aliases.items():
                lines.append(f"  {key} -> {mapping}")
            yield event.plain_result("\n".join(lines))

    @alias_group.command("batch")
    @permission_type(PermissionType.ADMIN)
    async def batch_alias(self, event: AstrMessageEvent, name: str, mapping: str):
        """
        专门设置一个批量映射别名，将其映射到一串连续执行的多个命令。
        这里的 mapping 为多个命令字符串，以分号分隔。
        
        用法: /alias batch <name> <mapping>
        
        示例: /alias batch combo "cmd1 arg; cmd2; cmd3"  
          当用户发送 "/combo extra" 时，将依次执行：
            /cmd1 arg extra
            /cmd2
            /cmd3
        """
        self.aliases[name] = mapping
        self._save_config()
        yield event.plain_result(f"已创建/更新批量别名 '{name}' -> '{mapping}'")

    @alias_group.command("test")
    @permission_type(PermissionType.ADMIN)
    async def test_command(self, event: AstrMessageEvent):
        """
        管理员测试命令，用于验证别名系统是否正常工作。
        
        用法: /alias test
        """
        yield event.plain_result("管理员测试命令执行成功。")

    # -----------------------------------------
    # 消息拦截：检测指令并批量重定向执行映射命令
    # -----------------------------------------
    @filter.event_message_type(EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        """
        拦截所有消息，若消息为指令（以 "/" 开头）且第一段匹配已注册别名，
        则将映射字符串拆分成多个命令依次发送，达到批量执行的效果。
        
        具体步骤：
        1. 移除指令前缀 "/"，提取首个单词作为别名，并获取余下参数。
        2. 如果别名存在，则将映射字符串以分号分割成多个命令。
        3. 对第一条命令附加用户输入的额外参数，其余命令原样执行。
        4. 依次调用 self.context.send_message 发送每个命令。
        5. 设置 _alias_processed 标记，调用 event.stop_event() 阻止后续处理。
        """
        if hasattr(event, "_alias_processed"):
            return

        text = event.message_str.strip()
        if not text.startswith("/"):
            return  # 非指令消息不处理

        # 提取调用的别名及后续参数
        without_prefix = text[1:]
        tokens = without_prefix.split(" ", 1)
        alias_name = tokens[0]
        extra_args = tokens[1] if len(tokens) > 1 else ""

        if alias_name in self.aliases:
            mapping = self.aliases[alias_name]
            # 拆分映射字符串：支持以分号分隔多个命令
            commands = [cmd.strip() for cmd in mapping.split(";") if cmd.strip()]
            if not commands:
                return
            # 第一条命令附加用户额外参数
            commands[0] = commands[0] + (" " + extra_args if extra_args else "")
            setattr(event, "_alias_processed", True)
            # 依次发送各条命令，确保执行顺序
            for cmd in commands:
                new_command = "/" + cmd.strip()
                await self.context.send_message(event.unified_msg_origin, [new_command])
            event.stop_event()
