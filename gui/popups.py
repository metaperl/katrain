from collections import defaultdict

from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label

from constants import OUTPUT_DEBUG, OUTPUT_ERROR
from engine import KataGoEngine
from game import Game, GameNode
from gui.kivyutils import (
    LabelledCheckBox,
    LabelledFloatInput,
    LabelledIntInput,
    LabelledObjectInputArea,
    LabelledSpinner,
    LabelledTextInput,
    ScaledLightLabel,
    StyledButton,
)


class InputParseError(Exception):
    pass


class QuickConfigGui(BoxLayout):
    def __init__(self, katrain, popup, initial_values=None):
        super().__init__()
        self.katrain = katrain
        self.popup = popup
        if initial_values:
            self.set_properties(self, initial_values)

    def collect_properties(self, widget):
        if isinstance(widget, (LabelledTextInput, LabelledSpinner)):
            try:
                ret = {widget.input_property: widget.input_value}
            except Exception as e:
                raise InputParseError(f"Could not parse value for {widget.input_property} ({widget.__class__}): {e}")
        else:
            ret = {}
        for c in widget.children:
            for k, v in self.collect_properties(c).items():
                ret[k] = v
        return ret

    def set_properties(self, widget, properties):
        if isinstance(widget, (LabelledTextInput, LabelledSpinner)):
            key = widget.input_property
            if key in properties:
                widget.text = str(properties[key])
        for c in widget.children:
            self.set_properties(c, properties)


class LoadSGFPopup(BoxLayout):
    pass


class NewGamePopup(QuickConfigGui):
    def __init__(self, katrain, popup, properties, **kwargs):
        properties["RU"] = KataGoEngine.get_rules(katrain.game.root)
        super().__init__(katrain, popup, properties)
        self.rules_spinner.values = list(set(self.katrain.engine.RULESETS.values()))
        self.rules_spinner.text = properties["RU"]

    def new_game(self):
        properties = self.collect_properties(self)
        self.katrain.log(f"New game settings: {properties}", OUTPUT_DEBUG)
        new_root = GameNode(properties={**Game.DEFAULT_PROPERTIES, **properties})
        x, y = new_root.board_size
        if x > 52 or y > 52:
            self.info.text = "Board size too big, should be at most 52"
            return
        self.katrain("new-game", new_root)
        self.popup.dismiss()


class ConfigPopup(QuickConfigGui):
    @staticmethod
    def type_to_widget_class(value):
        if isinstance(value, float):
            return LabelledFloatInput
        elif isinstance(value, bool):
            return LabelledCheckBox
        elif isinstance(value, int):
            return LabelledIntInput
        if isinstance(value, dict):
            return LabelledObjectInputArea
        else:
            return LabelledTextInput

    def __init__(self, katrain, popup, config, ignore_cats):
        self.config = config
        self.ignore_cats = ignore_cats
        self.orientation = "vertical"
        super().__init__(katrain, popup)
        Clock.schedule_once(self._build, 0)

    def _build(self, _):
        cols = [BoxLayout(orientation="vertical"), BoxLayout(orientation="vertical")]
        props_in_col = [0, 0]
        for k1, all_d in sorted(self.config.items(), key=lambda tup: -len(tup[1])):  # sort to make greedy bin packing work better
            if k1 in self.ignore_cats:
                continue
            d = {k: v for k, v in all_d.items() if isinstance(v, (int, float, str, bool))}  # no lists . dict could be supported but hard to scale
            cat = GridLayout(cols=2, rows=len(d) + 1, size_hint=(1, len(d) + 1))
            cat.add_widget(Label(text=""))
            cat.add_widget(ScaledLightLabel(text=f"{k1} settings", bold=True))
            for k2, v in d.items():
                cat.add_widget(ScaledLightLabel(text=f"{k2}:"))
                cat.add_widget(self.type_to_widget_class(v)(text=str(v), input_property=f"{k1}/{k2}"))
            if props_in_col[0] <= props_in_col[1]:
                cols[0].add_widget(cat)
                props_in_col[0] += len(d)
            else:
                cols[1].add_widget(cat)
                props_in_col[1] += len(d)

        col_container = BoxLayout(size_hint=(1, 0.9))
        col_container.add_widget(cols[0])
        col_container.add_widget(cols[1])
        self.add_widget(col_container)
        self.info_label = Label()
        self.apply_button = StyledButton(text="Apply", on_press=lambda _: self.update_config())
        self.save_button = StyledButton(text="Apply and Save", on_press=lambda _: self.update_config(save_to_file=True))
        btn_container = BoxLayout(orientation="horizontal", size_hint=(1, 0.1), spacing=1, padding=1)
        btn_container.add_widget(self.info_label)
        btn_container.add_widget(self.apply_button)
        btn_container.add_widget(self.save_button)
        self.add_widget(btn_container)

    def update_config(self, save_to_file=False):
        updated_cat = defaultdict(list)
        try:
            for k, v in self.collect_properties(self).items():
                k1, k2 = k.split("/")
                if self.config[k1][k2] != v:
                    self.katrain.log(f"Updating setting {k} = {v}", OUTPUT_DEBUG)
                    updated_cat[k1].append(k2)
                    self.config[k1][k2] = v
            self.popup.dismiss()
        except InputParseError as e:
            self.info_label.text = str(e)
            self.katrain.log(e, OUTPUT_ERROR)
            return

        if save_to_file:
            self.katrain.save_config()

        engine_updates = updated_cat["engine"]
        if "visits" in engine_updates:
            self.katrain.engine.visits = engine_updates["visits"]
        if {key for key in engine_updates if key not in {"max_visits", "max_time"}}:
            self.katrain.log(f"Restarting Engine after {engine_updates} settings change")
            self.katrain.controls.set_status(f"Restarting Engine after {engine_updates} settings change")
            old_engine = self.katrain.engine
            self.katrain.engine = KataGoEngine(self.katrain, self.config["engine"])
            self.katrain.game.engine = self.katrain.engine
            if getattr(old_engine, "katago_process"):
                old_engine.shutdown(finish=True)
            else:
                self.katrain.game.analyze_all_nodes()  # old engine was broken, so make sure we redo any failures

        self.katrain.update_state(redraw_board=True)
