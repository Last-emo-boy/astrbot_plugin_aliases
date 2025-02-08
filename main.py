from astrbot.api.all import *
from astrbot.core.log import LogManager
import os
import json
import copy

@register("alias_service", "w33d", "别名管理插件", "1.0.0", "https://github.com/Last-emo-boy/astrbot_plugin_aliases")
class AliasService(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.logger = LogManager.GetLogger("AliasService")
        self.alias_file = os.path.join(os.path.dirname(__file__), "alias_store.json")
        self._store = self.load_alias_store()
        self._setup_defaults()

    def _setup_defaults(self):
        """确保存储结构正确性"""
        if not isinstance(self._store, list):
            self.logger.warning("检测到损坏的存储结构，正在重置...")
            self._store = []

    def load_alias_store(self) -> list:
        try:
            if os.path.exists(self.alias_file):
                with open(self.alias_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            return []
        except Exception as e:
            self.logger.error(f"加载存储失败: {str(e)}")
            return []

    def save_alias_store(self):
        try:
            with open(self.alias_file, "w", encoding="utf-8") as f:
                json.dump(self._store, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.error(f"保存存储失败: {str(e)}")

    @command("alias.add")
    async def alias_add(self, event: AstrMessageEvent, alias_name: str, *commands: str):
        '''添加/更新别名
        格式：/alias.add <别名> <命令1> [命令2...]
        示例：/alias.add 更新 /system_prompt 你是一个助手 /reset
        '''
        if not commands:
            yield event.reply("请提供至少一个命令")
            return

        # 合并连续命令
        command_list = []
        current_cmd = []
        for part in commands:
            if part.startswith('/') and current_cmd:
                command_list.append(' '.join(current_cmd))
                current_cmd = [part]
            else:
                current_cmd.append(part)
        if current_cmd:
            command_list.append(' '.join(current_cmd))

        # 更新或新增
        exists = False
        for item in self._store:
            if item['name'] == alias_name:
                item['commands'] = command_list
                exists = True
                break
        if not exists:
            self._store.append({'name': alias_name, 'commands': command_list})
        
        self.save_alias_store()
        yield event.reply(f"别名 '{alias_name}' 已{'更新' if exists else '添加'}")

    @command("alias.remove")
    async def alias_remove(self, event: AstrMessageEvent, alias_name: str):
        '''删除别名'''
        original_count = len(self._store)
        self._store = [item for item in self._store if item['name'] != alias_name]
        
        if len(self._store) < original_count:
            self.save_alias_store()
            yield event.reply(f"别名 '{alias_name}' 已删除")
        else:
            yield event.reply("别名不存在")

    @command("alias.list")
    async def alias_list(self, event: AstrMessageEvent):
        '''列出所有别名'''
        if not self._store:
            yield event.reply("当前没有已定义的别名")
            return
            
        response = ["当前别名列表："]
        for item in self._store:
            cmds = '\n'.join([f"  → {cmd}" for cmd in item['commands']])
            response.append(f"{item['name']}:\n{cmds}")
        
        yield event.reply('\n'.join(response))

    @event_message_type(EventMessageType.ALL)
    @command(priority=999)  # 高优先级处理
    async def alias_handler(self, event: AstrMessageEvent):
        '''处理别名替换'''
        if getattr(event, '_alias_processed', False):
            return

        message = event.message_str.strip()
        for alias in self._store:
            alias_name = alias['name']
            if message.startswith(alias_name):
                args = message[len(alias_name):].strip()
                self.logger.debug(f"触发别名: {alias_name} 参数: {args}")
                
                event.stop_propagation()  # 阻止原始事件处理
                event._alias_processed = True

                # 生成新事件
                for cmd in alias['commands']:
                    processed_cmd = cmd.replace("{args}", args) if "{args}" in cmd else f"{cmd} {args}".strip()
                    new_event = copy.deepcopy(event)
                    new_event.message_str = processed_cmd
                    new_event._alias_processed = True  # 防止循环触发
                    
                    self.logger.debug(f"生成新命令: {processed_cmd}")
                    await self.context.get_event_queue().put(new_event)
                
                return