"""AT-SPI access over D-Bus with pipelined calls (docs/60).

libatspi and pyatspi query one property per round trip; on this phone that is
~50 ms per node (133 nodes of System Settings: 7.4 s). Qt does not implement
the AT-SPI cache (Cache.GetItems returns nothing), so each node still needs a
few calls, but sending a whole tree level at once overlaps the round trips:
100 nodes take ~70-100 ms.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from gi.repository import Gio, GLib

ACC = 'org.a11y.atspi.Accessible'
PROPS = 'org.freedesktop.DBus.Properties'
REGISTRY = ('org.a11y.atspi.Registry', '/org/a11y/atspi/accessible/root')
NULL_PATH = '/org/a11y/atspi/null'

# AtspiStateType bit numbers
ACTIVE, CHECKED, EDITABLE, ENABLED, EXPANDABLE, EXPANDED = 1, 4, 7, 8, 9, 10
FOCUSED, SELECTED, SENSITIVE, SHOWING, VISIBLE = 12, 23, 24, 25, 30


def has_state(states, bit: int) -> bool:
    return bool(states[bit // 32] & (1 << (bit % 32)))


@dataclass
class Node:
    bus: str
    path: str
    parent: 'Node | None'
    name: str = ''
    description: str = ''
    role: str = ''
    states: tuple = (0, 0)
    interfaces: tuple = ()
    accessible_id: str = ''
    children: list = field(default_factory=list)
    actions: tuple = ()          # action names, lower case
    value: object = None
    extents: tuple | None = None  # window-relative x, y, w, h

    def state(self, bit: int) -> bool:
        return has_state(self.states, bit)


class A11yBus:
    def __init__(self) -> None:
        self.session = Gio.bus_get_sync(Gio.BusType.SESSION)
        address = self.session.call_sync('org.a11y.Bus', '/org/a11y/bus', 'org.a11y.Bus', 'GetAddress', None,
                                         GLib.VariantType('(s)'), 0, 3000).unpack()[0]
        self.bus = Gio.DBusConnection.new_for_address_sync(
            address, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION)
        self.context = GLib.MainContext.default()

    # ---- accessibility switch (Qt apps register while it is on) --------------------
    def enabled(self) -> bool:
        value = self.session.call_sync('org.a11y.Bus', '/org/a11y/bus', PROPS, 'Get',
                                       GLib.Variant('(ss)', ('org.a11y.Status', 'IsEnabled')), None, 0, 3000)
        return bool(value.unpack()[0])

    def set_enabled(self, value: bool) -> None:
        self.session.call_sync('org.a11y.Bus', '/org/a11y/bus', PROPS, 'Set',
                               GLib.Variant('(ssv)', ('org.a11y.Status', 'IsEnabled', GLib.Variant('b', value))),
                               None, 0, 3000)

    # ---- calls ------------------------------------------------------------------------
    def batch(self, requests: list[tuple]) -> list:
        """Send (bus, path, interface, method, args) calls at once; results or exceptions in order."""
        results: list = [None] * len(requests)
        pending = [len(requests)]

        def done(connection, result, index):
            try:
                results[index] = connection.call_finish(result).unpack()
            except GLib.Error as error:
                results[index] = error
            pending[0] -= 1

        for index, (bus, path, interface, method, args) in enumerate(requests):
            self.bus.call(bus, path, interface, method, args, None, 0, 3000, None, done, index)
        deadline = time.monotonic() + 5
        while pending[0] and time.monotonic() < deadline:
            self.context.iteration(True)
        return results

    def call(self, bus, path, interface, method, args=None):
        result = self.batch([(bus, path, interface, method, args)])[0]
        if isinstance(result, Exception):
            raise result
        return result

    def pid(self, bus: str) -> int | None:
        try:
            return self.bus.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus',
                                      'GetConnectionUnixProcessID', GLib.Variant('(s)', (bus,)), None, 0,
                                      2000).unpack()[0]
        except GLib.Error:
            return None

    # ---- queries ----------------------------------------------------------------------
    def applications(self) -> list[tuple[str, str]]:
        return [tuple(child) for child in self.call(*REGISTRY, ACC, 'GetChildren')[0]]

    def windows(self, app: tuple[str, str]) -> list[Node]:
        children = self.call(app[0], app[1], ACC, 'GetChildren')[0]
        nodes = [Node(bus, path, None) for bus, path in children]
        self._fill(nodes)
        return nodes

    def tree(self, root: Node, *, max_nodes: int = 800, max_depth: int = 40) -> list[Node]:
        """Showing nodes below `root` (breadth first), each filled with basic properties."""
        self._fill([root])
        level, depth, out = [root], 0, [root]
        while level and depth < max_depth and len(out) < max_nodes:
            requests = [(n.bus, n.path, ACC, 'GetChildren', None) for n in level if n.state(SHOWING)]
            parents = [n for n in level if n.state(SHOWING)]
            next_level = []
            for parent, children in zip(parents, self.batch(requests)):
                if isinstance(children, Exception):
                    continue
                for bus, path in children[0]:
                    if path != NULL_PATH:
                        child = Node(bus, path, parent)
                        parent.children.append(child)
                        next_level.append(child)
            next_level = next_level[: max_nodes - len(out)]
            self._fill(next_level)
            level = [n for n in next_level if n.state(SHOWING)]
            out.extend(level)
            depth += 1
        return out

    def _fill(self, nodes: list[Node]) -> None:
        # Qt implements Properties.Get but not GetAll, so each property is its own call.
        requests = []
        for n in nodes:
            requests += [(n.bus, n.path, PROPS, 'Get', GLib.Variant('(ss)', (ACC, 'Name'))),
                         (n.bus, n.path, PROPS, 'Get', GLib.Variant('(ss)', (ACC, 'Description'))),
                         (n.bus, n.path, PROPS, 'Get', GLib.Variant('(ss)', (ACC, 'AccessibleId'))),
                         (n.bus, n.path, ACC, 'GetState', None),
                         (n.bus, n.path, ACC, 'GetRoleName', None),
                         (n.bus, n.path, ACC, 'GetInterfaces', None)]
        results = self.batch(requests)
        for index, n in enumerate(nodes):
            name, description, accessible_id, states, role, interfaces = results[index * 6:index * 6 + 6]
            n.name = str(name[0] or '') if not isinstance(name, Exception) else ''
            n.description = str(description[0] or '') if not isinstance(description, Exception) else ''
            n.accessible_id = str(accessible_id[0] or '') if not isinstance(accessible_id, Exception) else ''
            n.states = tuple(states[0]) if not isinstance(states, Exception) else (0, 0)
            n.role = role[0] if not isinstance(role, Exception) else ''
            n.interfaces = tuple(interfaces[0]) if not isinstance(interfaces, Exception) else ()

    def details(self, nodes: list[Node]) -> None:
        """Action names and current values of the given nodes."""
        requests, slots = [], []
        for n in nodes:
            if 'org.a11y.atspi.Action' in n.interfaces:
                requests.append((n.bus, n.path, 'org.a11y.atspi.Action', 'GetActions', None))
                slots.append((n, 'actions'))
            if 'org.a11y.atspi.Value' in n.interfaces:
                requests.append((n.bus, n.path, PROPS, 'Get', GLib.Variant('(ss)', ('org.a11y.atspi.Value', 'CurrentValue'))))
                slots.append((n, 'value'))
            elif 'org.a11y.atspi.Text' in n.interfaces and (n.state(EDITABLE) or 'org.a11y.atspi.EditableText' in n.interfaces):
                requests.append((n.bus, n.path, 'org.a11y.atspi.Text', 'GetText', GLib.Variant('(ii)', (0, 400))))
                slots.append((n, 'text'))
        for (n, kind), result in zip(slots, self.batch(requests)):
            if isinstance(result, Exception):
                continue
            if kind == 'actions':
                n.actions = tuple(str(a[0]).lower() for a in result[0])
            elif kind == 'value':
                n.value = result[0]
            else:
                n.value = result[0]

    def extents(self, node: Node) -> tuple | None:
        """Window-relative extents (Wayland clients know no global position)."""
        if 'org.a11y.atspi.Component' not in node.interfaces:
            return None
        try:
            x, y, w, h = self.call(node.bus, node.path, 'org.a11y.atspi.Component', 'GetExtents',
                                   GLib.Variant('(u)', (1,)))[0]
        except GLib.Error:
            return None
        return (x, y, w, h) if w > 0 and h > 0 else None

