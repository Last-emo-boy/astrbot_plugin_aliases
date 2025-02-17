from astrbot.api.all import *
from astrbot.core.log import LogManager  # 使用 LogManager 获取 logger
import os
import json
import shlex

@register("alias_service", "w33d", "别名管理插件", "1.0.0", "https://github.com/Last-emo-boy/astrbot_plugin_aliases")
class AliasService(Star):
    def __init__(self, context):
        super().__init__(context)
        self.logger = LogManager.GetLogger("AliasService")
        # 存储文件路径：当前插件目录下 alias_store.json
        self.alias_file = os.path.join(os.path.dirname(__file__), "alias_store.json")
        self._store = self.load_alias_store()  # 别名数据：列表，每个元素为 {"name": str, "commands": [str, ...]}
        self.alias_groups = {}

    def load_alias_store(self):
        if os.path.exists(self.alias_file):
            try:
                with open(self.alias_file, "r", encoding="utf8") as f:
                    data = json.load(f)
                    self.logger.debug("成功加载别名存储文件。")
                    return data
            except Exception as e:
                self.logger.error(f"加载别名存储失败：{e}")
                return []
        else:
            return []

    def save_alias_store(self):
        try:
            with open(self.alias_file, "w", encoding="utf8") as f:
                json.dump(self._store, f, ensure_ascii=False, indent=4)
            self.logger.debug("成功保存别名存储文件。")
        except Exception as e:
            self.logger.error(f"保存别名存储失败：{e}")

    @command("alias.switch")
    async def alias_switch(self, event: AstrMessageEvent, *, group: str = None):
        '''切换或查询当前频道的别名组'''
        session_id = event.session_id
        channel_data = self.context.get_channel_data(session_id) or {}
        if not group:
            current_groups = channel_data.get("aliasGroups", [])
            yield event.plain_result(f"当前频道的别名组: {', '.join(current_groups) if current_groups else '无'}")
            return
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
    async def alias_add(self, event: AstrMessageEvent, alias_name: str, *cmds: str):
        '''
        添加或更新别名，可映射到多个命令。

        示例：
          /alias.add 123 /provider 2 /reset

        意味着别名 "123" 映射到两个命令，依次执行 "/provider 2" 和 "/reset"。
        如果命令中包含空格，请使用引号包裹。
        '''
        if not alias_name or not cmds:
            yield event.plain_result("请提供别名和至少一个命令")
            return

        # 将 cmds 元组合并为一个字符串，然后用 shlex.split 拆分（以便支持命令中含有空格的情况）
        command_str = " ".join(cmds)
        tokens = shlex.split(command_str)
        commands_list = []
        current_cmd = ""
        for token in tokens:
            if token.startswith("/") and current_cmd:
                commands_list.append(current_cmd.strip())
                current_cmd = token
            else:
                if current_cmd:
                    current_cmd += " " + token
                else:
                    current_cmd = token
        if current_cmd:
            commands_list.append(current_cmd.strip())

        updated = False
        for alias in self._store:
            if alias.get("name") == alias_name:
                alias["commands"] = commands_list
                updated = True
                break
        if updated:
            yield event.plain_result(f"别名 {alias_name} 已更新")
            self.logger.debug(f"更新别名 {alias_name}: {commands_list}")
        else:
            self._store.append({
                "name": alias_name,
                "commands": commands_list
            })
            yield event.plain_result(f"成功添加别名 {alias_name}")
            self.logger.debug(f"新增别名 {alias_name}: {commands_list}")
        self.save_alias_store()

    @command("alias.remove")
    async def alias_remove(self, event: AstrMessageEvent, *, name: str):
        '''删除别名'''
        before_count = len(self._store)
        self._store = [alias for alias in self._store if alias.get("name") != name]
        if len(self._store) < before_count:
            yield event.plain_result(f"成功删除别名 {name}")
            self.logger.debug(f"删除别名 {name}")
            self.save_alias_store()
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
        '''
        监听所有消息，自动执行别名指令（支持命令组合 & 参数传递）。
        当检测到消息以已注册的别名开头时：
          1. 调用 event.stop_event() 阻止原始事件后续处理。
          2. 为别名对应的每条命令构造新的 AstrMessageEvent 对象，并注入事件队列供后续命令解析执行。
        '''
        if getattr(event, '_alias_processed', False):
            return

        message = event.message_str.strip()
        self.logger.debug(f"收到消息: {message}")

        for alias in self._store:
            alias_name = alias.get("name", "")
            if message.startswith(alias_name):
                remaining_args = message[len(alias_name):].strip()
                self.logger.debug(f"匹配到别名 {alias_name}，剩余参数: {remaining_args}")
                event.stop_event()  # 终止原始事件传播

                for cmd in alias["commands"]:
                    full_command = (cmd.replace("{args}", remaining_args)
                                    if "{args}" in cmd
                                    else f"{cmd} {remaining_args}".strip())
                    self.logger.debug(f"构造新命令: {full_command}")
                    new_event = AstrMessageEvent(
                        message_str = full_command,
                        message_obj = event.message_obj,
                        platform_meta = event.platform_meta,
                        session_id = event.session_id
                    )
                    new_event._alias_processed = False
                    await self.context.get_event_queue().put(new_event)
                return
