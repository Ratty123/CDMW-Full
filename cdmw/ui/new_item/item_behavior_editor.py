"""Remaining ItemInfo controls on the existing exact-value tree and task lane."""
from copy import deepcopy

from PySide6.QtCore import Qt

from cdmw.core.iteminfo_behavior import read_behavior_fields
from cdmw.domain.new_item.item_behavior import (ItemBehaviorSettings, BEHAVIOR_FIELDS, SUBITEM_TYPES,
    encode_behavior_settings)
from cdmw.services.active_ui_translation import translate_active_ui_text as tr
from cdmw.ui.new_item.choice_model import set_choice_rows
from cdmw.ui.new_item.item_definition_editor import ItemDefinitionEditor
from cdmw.ui.new_item.item_settings_editor import whole_number


def _labels():
    return {
        'item_type':tr('Item type'), 'category':tr('Item category'), 'equipment_type':tr('Equipment type'),
        'material_key':tr('Material key'), 'material_match':tr('Material match'), 'item_groups':tr('Intrinsic item groups'),
        'hackable_character_groups':tr('Hackable character groups'), 'stage':tr('Stage link'), 'advice':tr('Advice link'),
        'mission':tr('Mission link'), 'broken_prefix':tr('Broken-name prefix'), 'memo':tr('Item memo'),
        'filter_type':tr('Filter type'), 'default_texture':tr('Default texture'), 'emoji_texture':tr('Emoji texture'),
        'drop_stat_type':tr('Drop stat type'), 'drop_defaults':tr('Drop defaults'), 'default_subitem':tr('Default subitem'),
        'discard_y_bits':tr('Discard vertical offset (raw bits)'), 'discard_attach_terrain':tr('Attach discarded item to terrain'),
        'fixed_pages':tr('Fixed pages'), 'dynamic_pages':tr('Dynamic pages'), 'inspections':tr('Inspection entries'),
        'inspect_action':tr('Inspection action'), 'docking':tr('Attached item docking'),
        'inventory_change':tr('Inventory-change event'), 'money':tr('Currency definition'),
        'icons':tr('Conditional icons'), 'prefabs':tr('Prefab entries'),
        'left_texture':tr('Left page texture'), 'right_texture':tr('Right page texture'),
        'left_knowledge':tr('Left page knowledge'), 'right_knowledge':tr('Right page knowledge'),
        'item':tr('Item'), 'gimmick':tr('Gimmick'), 'character':tr('Character'), 'spawn_reason_hash':tr('Spawn reason hash'),
        'socket':tr('Socket'), 'speak_character':tr('Speaking character'), 'target_tag':tr('Target tag'),
        'reward_own_knowledge':tr('Reward own knowledge'), 'reward_knowledge':tr('Reward knowledge'),
        'description':tr('Description'), 'key':tr('Localization number'),
        'text_key':tr('Localization key'), 'board_key':tr('Board key'), 'action_type':tr('Action type'),
        'gimmick_state_hash':tr('Gimmick state hash'), 'target_page':tr('Target page'), 'left_page':tr('Left page'),
        'page_knowledge':tr('Page knowledge'), 'read_after_reward':tr('Allow reading after reward'),
        'refer_to_left_page':tr('Refer to left-page inspection'), 'effect':tr('Inspection effect'),
        'complete_effect':tr('Inspection completion effect'), 'action_hash':tr('Action hash'),
        'catch_tag_hash':tr('Catch tag hash'), 'catcher_socket':tr('Catcher socket'), 'target_socket':tr('Target socket'),
        'enchant_level':tr('Initial enchantment level'), 'socket_items':tr('Default socket items'),
        'socket_materials':tr('Socket unlock materials'), 'count':tr('Count'), 'subitem':tr('Drop subitem'),
        'type':tr('Subitem type'), 'value':tr('Value'), 'valid_sockets':tr('Valid socket count'), 'use_sockets':tr('Use sockets'),
        'parent_socket':tr('Parent socket'), 'child_socket':tr('Child socket'), 'docking_tags':tr('Docking tag hashes'),
        'equipment_slot':tr('Equipment slot'), 'spawn_distance':tr('Spawn distance (raw value)'),
        'equip_gimmick':tr('Equipment docking gimmick'), 'damage_parent':tr('Send damage to parent'),
        'body_part':tr('Body part'), 'docking_type':tr('Docking type'), 'summoner_team':tr('Use summoner team'),
        'player_only':tr('Player only'), 'npc_only':tr('NPC condition'), 'sync_break_parent':tr('Synchronize parent breaking'),
        'hit_part':tr('Hit part'), 'detected_by_npc':tr('Detected by NPCs'), 'bag_docking':tr('Bag docking'),
        'collision':tr('Enable collision'), 'disable_other_gimmick_collision':tr('Disable other gimmick collision'),
        'slot_key':tr('Docking slot key'), 'inherit_summoner':tr('Inherit summoner'), 'summon_tags':tr('Summon tag hashes'),
        'animation_root_bone':tr('Animation root bone'), 'event_type':tr('Game event type'),
        'player_condition':tr('Player condition'), 'target_condition':tr('Target condition'), 'event_condition':tr('Event condition'),
        'inventory':tr('Destination inventory'), 'price_floor':tr('Price floor (raw u64)'), 'units':tr('Currency units'),
        'unit':tr('Unit key'), 'ui_component':tr('UI component'), 'minimum':tr('Minimum'), 'icon':tr('Icon'),
        'money_icon':tr('Currency icon'), 'name':tr('Name'), 'highlight_icon':tr('Highlight icon'),
        'check_sealed':tr('Check sealed data'), 'gimmick_states':tr('Gimmick states'), 'check_usable':tr('Check usability'),
        'scale':tr('Prefab scale'), 'animations':tr('Animation paths'), 'equipment_slots':tr('Equipment slots'),
        'tribe_genders':tr('Tribe and gender selectors'), 'docking_switch':tr('Docking prefab switch'),
        'use_gimmick_prefab':tr('Use gimmick prefab'), 'craft_material':tr('Craft material'), 'data_type':tr('Prefab data type'),
    }


ROOT_REFERENCES = {'category':'categoryinfo','equipment_type':'equiptypeinfo','stage':'stageinfo',
    'advice':'gameadviceinfo','mission':'missioninfo','item_groups':'itemgroupinfo',
    'hackable_character_groups':'charactergroupinfo','default_texture':'texture','emoji_texture':'texture'}
LEAF_REFERENCES = {'item':'iteminfo','gimmick':'gimmickinfo','character':'characterinfo','speak_character':'characterinfo',
    'left_knowledge':'knowledgeinfo','right_knowledge':'knowledgeinfo','reward_knowledge':'knowledgeinfo',
    'page_knowledge':'knowledgeinfo','effect':'effectinfo','complete_effect':'effectinfo',
    'npc_only':'conditioninfo','player_condition':'conditioninfo','target_condition':'conditioninfo','event_condition':'conditioninfo',
    'left_texture':'texture','right_texture':'texture','icon':'stringinfo','money_icon':'stringinfo','highlight_icon':'stringinfo',
    'prefabs':'stringinfo','animations':'stringinfo','tribe_genders':'stringinfo','docking_switch':'stringinfo','text_key':'localization',
    'socket_items':'iteminfo'}


def _default(shape):
    if isinstance(shape,str):
        return False if shape=='bool' else '' if shape=='text' else 1.0 if shape=='f32' else {'type':17,'value':None} if shape=='subitem' else 0
    if shape[0]=='optional': return None
    if shape[0]=='record': return {name:_default(child) for name,child in shape[1]}
    if shape[0]=='array': return [_default(shape[1]) for _ in range(shape[2])]
    return []


class ItemBehaviorEditor(ItemDefinitionEditor):
    SETTINGS_ATTRIBUTE = 'behavior_settings'
    SETTINGS_TYPE = ItemBehaviorSettings
    INDEX_KIND = 'item-behavior'
    READ_FIELDS = staticmethod(read_behavior_fields)
    LABELS = staticmethod(_labels)

    def __init__(self,controller,parent=None):
        super().__init__(controller,parent)
        self.load.setText('Load behavior references')
        self._syncing=True
        set_choice_rows(self.section,((tr('Classification and links'),'classification'),(tr('Metadata'),'metadata'),
            (tr('Drop defaults'),'drops'),(tr('Pages and inspection'),'inspection'),
            (tr('Inventory events and docking'),'interaction'),(tr('Currency definition'),'currency'),
            (tr('Conditional icons and prefabs'),'presentation')))
        self._syncing=False
        self.description.hide()
        self.setToolTip('These settings require item.behavior version 1. Uncheck to inherit. Empty overridden lists clear; optional sections can be enabled or removed. Source references are checked. Raw selectors, hashes and timer units have unverified gameplay meanings.')
        self._section_changed()

    def _section_changed(self):
        self._syncing=True
        labels=self.LABELS(); group=self.section.currentData()
        set_choice_rows(self.field,tuple((labels[name],name) for name,(_field,_shape,section) in BEHAVIOR_FIELDS.items() if section==group))
        self._syncing=False; self.rebuild()

    def _description_rebuild(self,settings): self.description.hide()

    def _build(self,parent,value,path,label):
        if path and path[-1]=='category': label=tr('Localization category')
        super()._build(parent,value,path,label)

    def _commit(self,*,fields=None,**_unused):
        if self._syncing or self._source is None: return
        candidate=ItemBehaviorSettings(deepcopy(dict(self._settings().fields if fields is None else fields)))
        if not candidate.fields: candidate=None
        try:
            if candidate is not None: encode_behavior_settings(candidate)
        except (ValueError,TypeError): self._invalid(); return
        self.controller.draft.behavior_settings=candidate
        if self._editing_cell: self._display=deepcopy(candidate.fields[self.field.currentData()])
        self.controller.invalidate_plan(); self.message.clear(); self.rebuild()

    def _invalid(self):
        self.controller.invalidate_plan(); self.rebuild()
        self.message.setText('Invalid behavior value, range or record structure.')

    def _changed(self,item):
        if self._syncing or item.column()!=1 or not self.override.isChecked(): return
        path=tuple(item.data(self.PATH) or ()); original=self._at(self._display,path)
        self._editing_cell=True
        try:
            value=(item.checkState()==Qt.Checked if type(original) is bool else
                   whole_number(item.text(),0,(1<<64)-1) if type(original) is int else
                   float(item.text()) if type(original) is float else item.text())
            changed=self._assign(deepcopy(self._display),path,value)
            if path and path[-1]=='type':
                self._at(changed,path[:-1])['value']=0 if value in (0,3,9) else None
            self._field_commit(changed)
        except (ValueError,KeyError,TypeError): self._invalid()
        finally: self._editing_cell=False

    def _shape(self,path):
        shape=BEHAVIOR_FIELDS[self.field.currentData()][1]
        for part in path:
            if isinstance(shape,tuple) and shape[0]=='optional': shape=shape[1]
            if isinstance(shape,tuple) and shape[0]=='record': shape=dict(shape[1])[part]
            elif isinstance(shape,tuple): shape=shape[1]
            else: return 'u8' if part=='type' else 'u32'
        return shape

    def _reference_kind(self,path):
        name=self.field.currentData()
        if not path or (len(path)==1 and type(path[0]) is int):
            if name in ROOT_REFERENCES: return ROOT_REFERENCES[name]
        if not path: return None
        leaf=next((part for part in reversed(path) if type(part) is str),None)
        if leaf=='type': return 'subitem-type'
        if leaf=='value' and isinstance(self._at(self._display,path[:-1]),dict):
            return {3:'characterinfo',9:'gimmickinfo'}.get(self._at(self._display,path[:-1]).get('type'))
        return LEAF_REFERENCES.get(leaf)

    def _reference_choices(self):
        if self._syncing: return
        kind=self._reference_kind(self._selected_path()) if self._source is not None else None
        rows=()
        if self.index is not None:
            if kind=='localization': rows=tuple((key,key) for key in self.index.localizations)
            else: rows=tuple((f'{label} ({key})',key) for key,label in self.index.choices.get(kind,()))
        if kind=='subitem-type': rows=tuple((str(key),key) for key in sorted(SUBITEM_TYPES))
        set_choice_rows(self.picker,rows)
        enabled=self.override.isChecked()
        self.use.setEnabled(bool(rows) and enabled); self.add.setEnabled(enabled); self.remove.setEnabled(enabled)
        list_path=self._list_path()
        if list_path is not None:
            shape=self._shape(list_path)
            if isinstance(shape,tuple) and shape[0]=='array': self.add.setEnabled(False)
        self.add.setText('Enable section' if self._display is None else 'Add entry')

    def _use_reference(self):
        path,value=self._selected_path(),self.picker.currentData()
        if value is None or not self.override.isChecked(): return
        changed=deepcopy(self._display); kind=self._reference_kind(path)
        if kind=='localization': self._at(changed,path[:-1]).update(self.index.localizations[value])
        else:
            changed=self._assign(changed,path,value)
            if kind=='subitem-type': self._at(changed,path[:-1])['value']=0 if value in (0,3,9) else None
        self._field_commit(changed)

    def _entry(self,path,values):
        return _default(self._shape(path)[1])

    def _add(self):
        shape=BEHAVIOR_FIELDS[self.field.currentData()][1]
        if self.override.isChecked() and self._display is None and isinstance(shape,tuple) and shape[0]=='optional':
            self._field_commit(_default(shape[1])); return
        super()._add()

    def _remove(self):
        shape=BEHAVIOR_FIELDS[self.field.currentData()][1]
        if self.override.isChecked() and not self._selected_path() and isinstance(shape,tuple) and shape[0]=='optional':
            self._field_commit(None); return
        # Fixed arrays (scale and four-word tag hashes) cannot be resized.
        for index in self.tree.selectionModel().selectedRows():
            path=tuple(index.data(self.PATH) or ())
            if path and isinstance(self._shape(path[:-1]),tuple) and self._shape(path[:-1])[0]=='array': return
        super()._remove()
