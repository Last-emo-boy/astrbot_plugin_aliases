from astrbot.api.all import *
from astrbot.core.log import LogManager  # 使用 LogManager 获取 logger
from typing import List, Dict, Any
import shlex
import os
import json
# 注意：不再使用 copy 拷贝事件，而是直接构造新的事件对象

@register("alias_service", "w33d", "别名管理插件", "1.0.0", "https://github.com/Last-emo-boy/astrbot_plugin_aliases")
class AliasService(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.logger = LogManager.GetLogger("AliasService")
        # 持久化文件路径，存放在当前插件目录下的 alias_store.json
        self.alias_file = os.path.join(os.path.dirname(__file__), "alias_store.json")
        self._store: List[Dict[str, Any]] = self.load_alias_store()
        # 别名组（如果需要持久化可以扩展此部分，此处仅作临时存储）
        self.alias_groups: Dict[str, List[str]] = {}

    def load_alias_store(self) -> List[Dict[str, Any]]:
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
    async def alias_add(self, event: AstrMessageEvent, *, name: str, commands: str):
        '''
        添加或更新别名，可映射到多个命令。
        
        示例：
          /alias.add 123 /provider 2 /reset
        
        意味着别名 "123" 映射到两个命令，依次执行 “/provider 2” 和 “/reset”。
        如果命令中包含空格，请使用引号包裹。
        '''
        if not commands:
            yield event.plain_result("请输入别名对应的命令")
            return

        # 利用 shlex.split 将输入拆分成 token，然后按“遇到以 '/' 开头的新 token”进行分组
        tokens = shlex.split(commands)
        cmds = []
        current_cmd = ""
        for token in tokens:
            if token.startswith("/") and current_cmd:
                cmds.append(current_cmd.strip())
                current_cmd = token
            else:
                if current_cmd:
                    current_cmd += " " + token
                else:
                    current_cmd = token
        if current_cmd:
            cmds.append(current_cmd.strip())

        updated = False
        for alias in self._store:
            if alias.get("name") == name:
                alias["commands"] = cmds
                updated = True
                break
        if updated:
            yield event.plain_result(f"别名 {name} 已更新")
            self.logger.debug(f"更新别名 {name}: {cmds}")
        else:
            self._store.append({
                "name": name,
                "commands": cmds
            })
            yield event.plain_result(f"成功添加别名 {name}")
            self.logger.debug(f"新增别名 {name}: {cmds}")
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

    async def on_message(self, event: AstrMessageEvent):
        '''
        监听所有消息，自动执行别名指令（支持命令组合 & 参数传递）。
        当检测到消息以已注册的别名开头时：
          1. 调用 event.stop_event() 阻止原始事件后续处理（避免触发 LLM 等其它流程）。
          2. 为别名对应的每条命令构造新的 AstrMessageEvent 对象，并注入事件队列供后续命令解析执行。
        '''
        # 如果该事件已被处理过，则跳过
        if getattr(event, '_alias_processed', False):
            return

        message = event.message_str.strip()
        self.logger.debug(f"收到消息: {message}")

        for alias in self._store:
            alias_name = alias.get("name", "")
            if message.startswith(alias_name):
                remaining_args = message[len(alias_name):].strip()
                self.logger.debug(f"匹配到别名 {alias_name}，剩余参数: {remaining_args}")
                # 停止原始事件后续处理
                event.stop_event()
                # 依次构造新的命令事件并注入队列
                for cmd in alias["commands"]:
                    # 如果命令中包含 {args} 占位符则进行替换，否则直接追加剩余参数
                    full_command = cmd.replace("{args}", remaining_args) if "{args}" in cmd else f"{cmd} {remaining_args}".strip()
                    self.logger.debug(f"准备注入执行命令: {full_command}")
                    # 构造新的事件；注意这里只填入必要字段，请根据实际情况补充其它字段
                    new_event = AstrMessageEvent(
                        message_str=full_command,
                        session_id=event.session_id,
                        unified_msg_origin=event.unified_msg_origin,
                        raw_message=event.raw_message  # 复用原始消息对象
                    )
                    # 不设置 _alias_processed 标志（或确保为 False），以便新事件能被正常解析
                    new_event._alias_processed = False
                    # 注入事件队列（使用 put 以确保异步等待队列处理）
                    await self.context.get_event_queue().put(new_event)
                return
