from astrbot.api.all import *
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import MessageChain
from typing import List, Dict, Any

@register("alias_service", "w33d", "", "1.0.0", "https://github.com/Last-emo-boy/astrbot_plugin_aliases")
class AliasService(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        # 存储所有别名，格式为：{"name": str, "commands": List[str]}
        self._store: List[Dict[str, Any]] = []
        # 记录别名组（如果需要支持别名组的创建，可预设或在其他地方补充管理逻辑）
        self.alias_groups: Dict[str, List[str]] = {}
        # 获取日志记录器，使用开发文档推荐的方式
        self.logger = self.context.get_logger("AliasService")

    @command("alias.switch")
    async def alias_switch(self, event: AstrMessageEvent, group: str = None):
        '''切换或查询当前频道的别名组'''
        session_id = event.session_id  
        channel_data = self.context.get_channel_data(session_id) or {}

        if not group:
            current_groups = channel_data.get("aliasGroups", [])
            yield event.plain_result(f"当前频道的别名组: {', '.join(current_groups) if current_groups else '无'}")
            return

        # 检查别名组是否存在（此处可根据需求扩展别名组的创建与管理逻辑）
        if group not in self.alias_groups:
            yield event.plain_result("未找到对应的别名组")
            return

        if group in channel_data.get("aliasGroups", []):
            yield event.plain_result(f"频道已在别名组 {group}，未改动")
            return

        channel_data["aliasGroups"] = [group]
        self.context.update_channel_data(session_id, channel_data)
        yield event.plain_result(f"成功切换到别名组 {group}")
        self.logger.debug(f"频道 {session_id} 已切换到别名组 {group}")

    @command("alias.add")
    async def alias_add(self, event: AstrMessageEvent, name: str, *commands: str):
        '''添加或更新别名，可映射到多个命令'''
        if not commands:
            yield event.plain_result("请输入别名对应的命令")
            return

        commands_list = list(commands)
        # 检查是否已存在该别名，若存在则更新其对应的命令
        for alias in self._store:
            if alias.get("name") == name:
                alias["commands"] = commands_list
                yield event.plain_result(f"别名 {name} 已更新")
                self.logger.debug(f"更新别名 {name}: {commands_list}")
                return

        # 添加新的别名
        self._store.append({
            "name": name,
            "commands": commands_list
        })
        yield event.plain_result(f"成功添加别名 {name}")
        self.logger.debug(f"新增别名 {name}: {commands_list}")

    @command("alias.remove")
    async def alias_remove(self, event: AstrMessageEvent, name: str):
        '''删除别名'''
        before_count = len(self._store)
        self._store = [alias for alias in self._store if alias.get("name") != name]
        if len(self._store) < before_count:
            yield event.plain_result(f"成功删除别名 {name}")
            self.logger.debug(f"删除别名 {name}")
        else:
            yield event.plain_result(f"别名 {name} 不存在")

    @command("alias.list")
    async def alias_list(self, event: AstrMessageEvent):
        '''列出所有别名'''
        if not self._store:
            yield event.plain_result("当前没有别名")
            return

        alias_str = "\n".join([f"{alias['name']} -> {' | '.join(alias['commands'])}" for alias in self._store])
        yield event.plain_result(f"当前别名列表:\n{alias_str}")

    @event_message_type(EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        '''监听所有消息，自动执行别名指令（支持命令组合 & 参数传递）'''
        if not isinstance(event, AstrMessageEvent):
            self.logger.error("on_message 事件参数错误，event 不是 AstrMessageEvent")
            return

        message = event.message_str.strip()
        self.logger.debug(f"收到消息: {message}")

        # 遍历别名，判断是否匹配到消息的开头
        for alias in self._store:
            alias_name = alias.get("name", "")
            if message.startswith(alias_name):
                remaining_args = message[len(alias_name):].strip()
                self.logger.debug(f"匹配到别名 {alias_name}，参数: {remaining_args}")

                # 遍历该别名映射的命令，支持 {args} 占位符替换或直接追加参数
                for cmd in alias["commands"]:
                    full_command = cmd.replace("{args}", remaining_args) if "{args}" in cmd else f"{cmd} {remaining_args}".strip()
                    self.logger.debug(f"执行命令: {full_command}")
                    await self.context.send_message(event.unified_msg_origin, MessageChain().message(full_command))
                # 只执行第一个匹配的别名，后续别名不再处理
                return
