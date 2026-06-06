# This is a generated file! Please edit source .ksy file and use kaitai-struct-compiler to rebuild

import kaitaistruct
from kaitaistruct import KaitaiStruct, KaitaiStream, BytesIO
from enum import Enum
import zlib


if getattr(kaitaistruct, 'API_VERSION', (0, 9)) < (0, 9):
    raise Exception("Incompatible Kaitai Struct Python API: 0.9 or later is required, but you have %s" % (kaitaistruct.__version__))

class TwMapV4(KaitaiStruct):
    """
    .. seealso::
       Source - https://github.com/heinrich5991/libtw2/blob/b510f20bc58ceb33f38ddc555b63989ccf5a90d7/doc/datafile.md
    """

    class EnvelopeKind(Enum):
        volume = 1
        position = 3
        color = 4

    class CurveKind(Enum):
        step = 0
        linear = 1
        slow = 2
        fast = 3
        smooth = 4
        bezier = 5

    class LayerFlags(Enum):
        not_quality = 0
        quality = 1

    class LayerKind(Enum):
        tilemap = 2
        quads = 3
        deprecated_sounds = 9
        sounds = 10

    class Optional(Enum):
        not_set = -1

    class TilemapFlags(Enum):
        tiles = 0
        game = 1
        tele = 16
        speedup = 256
        front = 4096
        switch = 65536
        tune = 1048576

    class ItemKind(Enum):
        version = 0
        info = 1
        image = 2
        envelope = 3
        group = 4
        layer = 5
        env_points = 6
        sound = 7
        ex_type_index = 65535

    class Bool(Enum):
        false = 0
        true = 1

    class SoundSourceShape(Enum):
        rectangle = 0
        circle = 1
    def __init__(self, _io, _parent=None, _root=None):
        self._io = _io
        self._parent = _parent
        self._root = _root if _root else self
        self._read()

    def _read(self):
        self.header = TwMapV4.Header(self._io, self, self._root)
        self.item_types = []
        for i in range(self.header.num_item_types):
            self.item_types.append(TwMapV4.ItemType(self._io, self, self._root))

        self.item_offsets = []
        for i in range(self.header.num_items):
            self.item_offsets.append(self._io.read_s4le())

        self.data_offsets = []
        for i in range(self.header.num_data):
            self.data_offsets.append(self._io.read_s4le())

        self.data_sizes = []
        for i in range(self.header.num_data):
            self.data_sizes.append(self._io.read_s4le())

        self.items = []
        for i in range(self.header.num_items):
            self.items.append(TwMapV4.Item(self._io, self, self._root))

        self._raw_data_items = []
        self._raw__raw_data_items = []
        self.data_items = []
        for i in range(self.header.num_data):
            self._raw__raw_data_items.append(self._io.read_bytes(((self.header.data_size if i == (self.header.num_data - 1) else self.data_offsets[(i + 1)]) - self.data_offsets[i])))
            self._raw_data_items.append(zlib.decompress(self._raw__raw_data_items[i]))
            _io__raw_data_items = KaitaiStream(BytesIO(self._raw_data_items[i]))
            self.data_items.append(TwMapV4.Dummy(_io__raw_data_items, self, self._root))


    class OptionalStringDataIndex(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._read()

        def _read(self):
            self.data_index = self._io.read_s4le()

        @property
        def string(self):
            if hasattr(self, '_m_string'):
                return self._m_string

            if self.data_index != -1:
                io = self._root.data_items[self.data_index]._io
                self._m_string = (io.read_bytes_full()).decode(u"UTF-8")

            return getattr(self, '_m_string', None)


    class OptionalMultipleStringsDataIndex(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._read()

        def _read(self):
            self.data_index = self._io.read_s4le()

        @property
        def strings(self):
            if hasattr(self, '_m_strings'):
                return self._m_strings

            if self.data_index != -1:
                io = self._root.data_items[self.data_index]._io
                self._m_strings = []
                i = 0
                while not io.is_eof():
                    self._m_strings.append((io.read_bytes_term(0, False, True, True)).decode(u"UTF-8"))
                    i += 1


            return getattr(self, '_m_strings', None)


    class TilemapLayerItem(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._read()

        def _read(self):
            self.version = self._io.read_s4le()
            self.width = self._io.read_s4le()
            self.height = self._io.read_s4le()
            self.type = KaitaiStream.resolve_enum(TwMapV4.TilemapFlags, self._io.read_s4le())
            self.color = TwMapV4.Color(self._io, self, self._root)
            self.color_envelope_index = self._io.read_s4le()
            self.color_envelope_offset = self._io.read_s4le()
            self.image_index = KaitaiStream.resolve_enum(TwMapV4.Optional, self._io.read_s4le())
            self.tiles_data_index = self._io.read_s4le()
            self.name = TwMapV4.I32x3String(self._io, self, self._root)
            if not (self._io.is_eof()):
                self.tele_data_index = KaitaiStream.resolve_enum(TwMapV4.Optional, self._io.read_s4le())

            if not (self._io.is_eof()):
                self.speedup_data_index = KaitaiStream.resolve_enum(TwMapV4.Optional, self._io.read_s4le())

            if not (self._io.is_eof()):
                self.front_data_index = KaitaiStream.resolve_enum(TwMapV4.Optional, self._io.read_s4le())

            if not (self._io.is_eof()):
                self.switch_data_index = KaitaiStream.resolve_enum(TwMapV4.Optional, self._io.read_s4le())

            if not (self._io.is_eof()):
                self.tune_data_index = KaitaiStream.resolve_enum(TwMapV4.Optional, self._io.read_s4le())



    class QuadsLayerItem(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._read()

        def _read(self):
            self.version = self._io.read_s4le()
            self.quad_amount = self._io.read_s4le()
            self.data_index = self._io.read_s4le()
            self.image_index = KaitaiStream.resolve_enum(TwMapV4.Optional, self._io.read_s4le())
            if self.version >= 2:
                self.name = TwMapV4.I32x3String(self._io, self, self._root)


        @property
        def quads(self):
            if hasattr(self, '_m_quads'):
                return self._m_quads

            io = self._root.data_items[self.data_index]._io
            self._m_quads = []
            i = 0
            while not io.is_eof():
                self._m_quads.append(TwMapV4.Quad(io, self, self._root))
                i += 1

            return getattr(self, '_m_quads', None)


    class ExTypeIndexItem(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._read()

        def _read(self):
            self.uuid = self._io.read_bytes(16)


    class GroupItem(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._read()

        def _read(self):
            self.version = self._io.read_s4le()
            self.offset = TwMapV4.FixedPoint(32, self._io, self, self._root)
            self.parallax = TwMapV4.FixedPoint(100, self._io, self, self._root)
            self.first_layer_index = self._io.read_s4le()
            self.layer_amount = self._io.read_s4le()
            if self.version >= 2:
                self.clipping = KaitaiStream.resolve_enum(TwMapV4.Bool, self._io.read_s4le())

            if self.version >= 2:
                self.clip_position = TwMapV4.FixedPoint(32, self._io, self, self._root)

            if self.version >= 2:
                self.clip_size = TwMapV4.FixedPoint(32, self._io, self, self._root)

            self.name = TwMapV4.I32x3String(self._io, self, self._root)


    class SoundSource(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._read()

        def _read(self):
            self.position = TwMapV4.FixedPoint((1024 * 32), self._io, self, self._root)
            self.looping = KaitaiStream.resolve_enum(TwMapV4.Bool, self._io.read_s4le())
            self.panning = KaitaiStream.resolve_enum(TwMapV4.Bool, self._io.read_s4le())
            self.delay = self._io.read_s4le()
            self.falloff = self._io.read_s4le()
            self.position_envelope_index = KaitaiStream.resolve_enum(TwMapV4.Optional, self._io.read_s4le())
            self.position_envelope_offset = self._io.read_s4le()
            self.sound_envelope_index = KaitaiStream.resolve_enum(TwMapV4.Optional, self._io.read_s4le())
            self.sound_envelope_offset = self._io.read_s4le()
            self.shape = KaitaiStream.resolve_enum(TwMapV4.SoundSourceShape, self._io.read_s4le())
            self.dimensions = TwMapV4.FixedPoint((1024 * 32), self._io, self, self._root)


    class ImageItem(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._read()

        def _read(self):
            self.version = self._io.read_s4le()
            self.width = self._io.read_s4le()
            self.height = self._io.read_s4le()
            self.external = KaitaiStream.resolve_enum(TwMapV4.Bool, self._io.read_s4le())
            self.name = TwMapV4.OptionalStringDataIndex(self._io, self, self._root)
            self.data_index = KaitaiStream.resolve_enum(TwMapV4.Optional, self._io.read_s4le())


    class Color(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._read()

        def _read(self):
            self.r = self._io.read_s4le()
            self.g = self._io.read_s4le()
            self.b = self._io.read_s4le()
            self.a = self._io.read_s4le()


    class Dummy(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._read()

        def _read(self):
            pass


    class EnvPoint(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._read()

        def _read(self):
            self.time = self._io.read_s4le()
            self.curve_type = KaitaiStream.resolve_enum(TwMapV4.CurveKind, self._io.read_s4le())
            self.values = []
            for i in range(4):
                self.values.append(self._io.read_s4le())


        @property
        def time_ms(self):
            if hasattr(self, '_m_time_ms'):
                return self._m_time_ms

            self._m_time_ms = (self.time / 1000)
            return getattr(self, '_m_time_ms', None)


    class VersionItem(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._read()

        def _read(self):
            self.version = self._io.read_s4le()


    class Quad(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._read()

        def _read(self):
            self.top_left_position = TwMapV4.FixedPoint((1024 * 32), self._io, self, self._root)
            self.top_right_position = TwMapV4.FixedPoint((1024 * 32), self._io, self, self._root)
            self.bot_left_position = TwMapV4.FixedPoint((1024 * 32), self._io, self, self._root)
            self.bot_right_position = TwMapV4.FixedPoint((1024 * 32), self._io, self, self._root)
            self.position = TwMapV4.FixedPoint((1024 * 32), self._io, self, self._root)
            self.corner_colors = []
            for i in range(4):
                self.corner_colors.append(TwMapV4.Color(self._io, self, self._root))

            self.texture_coordinates = []
            for i in range(4):
                self.texture_coordinates.append(TwMapV4.FixedPoint(1024, self._io, self, self._root))

            self.position_envelope_index = KaitaiStream.resolve_enum(TwMapV4.Optional, self._io.read_s4le())
            self.position_envelope_offset = self._io.read_s4le()
            self.color_envelope_index = KaitaiStream.resolve_enum(TwMapV4.Optional, self._io.read_s4le())
            self.color_envelope_offset = self._io.read_s4le()


    class SoundsLayerItem(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._read()

        def _read(self):
            self.version = self._io.read_s4le()
            self.source_amount = self._io.read_s4le()
            self.data_index = self._io.read_s4le()
            self.sound_index = KaitaiStream.resolve_enum(TwMapV4.Optional, self._io.read_s4le())
            self.name = TwMapV4.I32x3String(self._io, self, self._root)

        @property
        def sound_sources(self):
            if hasattr(self, '_m_sound_sources'):
                return self._m_sound_sources

            io = self._root.data_items[self.data_index]._io
            self._m_sound_sources = []
            i = 0
            while not io.is_eof():
                self._m_sound_sources.append(TwMapV4.SoundSource(io, self, self._root))
                i += 1

            return getattr(self, '_m_sound_sources', None)


    class EnvelopeItem(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._read()

        def _read(self):
            self.version = self._io.read_s4le()
            self.kind = KaitaiStream.resolve_enum(TwMapV4.EnvelopeKind, self._io.read_s4le())
            self.first_point_index = self._io.read_s4le()
            self.envelope_amount = self._io.read_s4le()
            if not (self._io.is_eof()):
                self.name = TwMapV4.I32x8String(self._io, self, self._root)

            if self.version >= 2:
                self.synchronized = KaitaiStream.resolve_enum(TwMapV4.Bool, self._io.read_s4le())



    class FixedPoint(KaitaiStruct):
        def __init__(self, divisor, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self.divisor = divisor
            self._read()

        def _read(self):
            self.x_raw = self._io.read_s4le()
            self.y_raw = self._io.read_s4le()

        @property
        def x(self):
            if hasattr(self, '_m_x'):
                return self._m_x

            self._m_x = (self.x_raw / self.divisor)
            return getattr(self, '_m_x', None)

        @property
        def y(self):
            if hasattr(self, '_m_y'):
                return self._m_y

            self._m_y = (self.y_raw / self.divisor)
            return getattr(self, '_m_y', None)


    class InfoItem(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._read()

        def _read(self):
            self.item_version = self._io.read_s4le()
            self.author = TwMapV4.OptionalStringDataIndex(self._io, self, self._root)
            self.version = TwMapV4.OptionalStringDataIndex(self._io, self, self._root)
            self.credits = TwMapV4.OptionalStringDataIndex(self._io, self, self._root)
            self.license = TwMapV4.OptionalStringDataIndex(self._io, self, self._root)
            if not (self._io.is_eof()):
                self.settings = TwMapV4.OptionalMultipleStringsDataIndex(self._io, self, self._root)



    class Header(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._read()

        def _read(self):
            self.magic = self._io.read_bytes(4)
            if not self.magic == b"\x44\x41\x54\x41":
                raise kaitaistruct.ValidationNotEqualError(b"\x44\x41\x54\x41", self.magic, self._io, u"/types/header/seq/0")
            self.version = self._io.read_bytes(4)
            if not self.version == b"\x04\x00\x00\x00":
                raise kaitaistruct.ValidationNotEqualError(b"\x04\x00\x00\x00", self.version, self._io, u"/types/header/seq/1")
            self.size = self._io.read_s4le()
            self.swaplen = self._io.read_s4le()
            self.num_item_types = self._io.read_s4le()
            self.num_items = self._io.read_s4le()
            self.num_data = self._io.read_s4le()
            self.item_size = self._io.read_s4le()
            self.data_size = self._io.read_s4le()


    class UnknownItem(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._read()

        def _read(self):
            self.item_data = []
            i = 0
            while not self._io.is_eof():
                self.item_data.append(self._io.read_s4le())
                i += 1



    class SoundItem(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._read()

        def _read(self):
            self.version = self._io.read_s4le()
            self.external = KaitaiStream.resolve_enum(TwMapV4.Bool, self._io.read_s4le())
            self.name = TwMapV4.OptionalStringDataIndex(self._io, self, self._root)
            self.data_index = self._io.read_s4le()


    class EnvPointsItem(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._read()

        def _read(self):
            pass

        @property
        def ddnet_points(self):
            if hasattr(self, '_m_ddnet_points'):
                return self._m_ddnet_points

            io = self._io
            self._m_ddnet_points = []
            i = 0
            while not io.is_eof():
                self._m_ddnet_points.append(TwMapV4.EnvPoint(io, self, self._root))
                i += 1

            return getattr(self, '_m_ddnet_points', None)

        @property
        def teeworlds07_points(self):
            if hasattr(self, '_m_teeworlds07_points'):
                return self._m_teeworlds07_points

            io = self._io
            self._m_teeworlds07_points = []
            i = 0
            while not io.is_eof():
                self._m_teeworlds07_points.append(TwMapV4.EnvPointWithBezier(io, self, self._root))
                i += 1

            return getattr(self, '_m_teeworlds07_points', None)


    class LayerItem(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._read()

        def _read(self):
            self.unused_version = self._io.read_s4le()
            self.type = KaitaiStream.resolve_enum(TwMapV4.LayerKind, self._io.read_s4le())
            self.flags = KaitaiStream.resolve_enum(TwMapV4.LayerFlags, self._io.read_s4le())
            _on = self.type
            if _on == TwMapV4.LayerKind.tilemap:
                self.content = TwMapV4.TilemapLayerItem(self._io, self, self._root)
            elif _on == TwMapV4.LayerKind.quads:
                self.content = TwMapV4.QuadsLayerItem(self._io, self, self._root)
            elif _on == TwMapV4.LayerKind.sounds:
                self.content = TwMapV4.SoundsLayerItem(self._io, self, self._root)


    class Bezier(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._read()

        def _read(self):
            self.handle_in = TwMapV4.FixedPoint(1024, self._io, self, self._root)
            self.handle_out = TwMapV4.FixedPoint(1024, self._io, self, self._root)


    class EnvPointWithBezier(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._read()

        def _read(self):
            self.point = TwMapV4.EnvPoint(self._io, self, self._root)
            self.bezier = TwMapV4.Bezier(self._io, self, self._root)


    class I32x3String(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._read()

        def _read(self):
            self._raw_data = []
            self.data = []
            for i in range(3):
                self._raw_data.append(self._io.read_bytes(4))
                self.data.append(KaitaiStream.process_xor_one(self._raw_data[i], 128))


        @property
        def string(self):
            if hasattr(self, '_m_string'):
                return self._m_string

            self._m_string = ((self.data[0]).decode(u"UTF-8"))[::-1] + ((self.data[1]).decode(u"UTF-8"))[::-1] + (((self.data[2]).decode(u"UTF-8"))[1:4])[::-1]
            return getattr(self, '_m_string', None)


    class I32x8String(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._read()

        def _read(self):
            self._raw_data = []
            self.data = []
            for i in range(8):
                self._raw_data.append(self._io.read_bytes(4))
                self.data.append(KaitaiStream.process_xor_one(self._raw_data[i], 128))


        @property
        def string(self):
            if hasattr(self, '_m_string'):
                return self._m_string

            self._m_string = ((self.data[0]).decode(u"UTF-8"))[::-1] + ((self.data[1]).decode(u"UTF-8"))[::-1] + ((self.data[2]).decode(u"UTF-8"))[::-1] + ((self.data[3]).decode(u"UTF-8"))[::-1] + ((self.data[4]).decode(u"UTF-8"))[::-1] + ((self.data[5]).decode(u"UTF-8"))[::-1] + ((self.data[6]).decode(u"UTF-8"))[::-1] + (((self.data[7]).decode(u"UTF-8"))[1:4])[::-1]
            return getattr(self, '_m_string', None)


    class ItemType(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._read()

        def _read(self):
            self.type_id = KaitaiStream.resolve_enum(TwMapV4.ItemKind, self._io.read_s4le())
            self.start = self._io.read_s4le()
            self.num = self._io.read_s4le()


    class Item(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._read()

        def _read(self):
            self.id = self._io.read_u2le()
            self.type_id = KaitaiStream.resolve_enum(TwMapV4.ItemKind, self._io.read_u2le())
            self.data_size = self._io.read_s4le()
            _on = self.type_id
            if _on == TwMapV4.ItemKind.info:
                self._raw_content = self._io.read_bytes(self.data_size)
                _io__raw_content = KaitaiStream(BytesIO(self._raw_content))
                self.content = TwMapV4.InfoItem(_io__raw_content, self, self._root)
            elif _on == TwMapV4.ItemKind.version:
                self._raw_content = self._io.read_bytes(self.data_size)
                _io__raw_content = KaitaiStream(BytesIO(self._raw_content))
                self.content = TwMapV4.VersionItem(_io__raw_content, self, self._root)
            elif _on == TwMapV4.ItemKind.layer:
                self._raw_content = self._io.read_bytes(self.data_size)
                _io__raw_content = KaitaiStream(BytesIO(self._raw_content))
                self.content = TwMapV4.LayerItem(_io__raw_content, self, self._root)
            elif _on == TwMapV4.ItemKind.env_points:
                self._raw_content = self._io.read_bytes(self.data_size)
                _io__raw_content = KaitaiStream(BytesIO(self._raw_content))
                self.content = TwMapV4.EnvPointsItem(_io__raw_content, self, self._root)
            elif _on == TwMapV4.ItemKind.image:
                self._raw_content = self._io.read_bytes(self.data_size)
                _io__raw_content = KaitaiStream(BytesIO(self._raw_content))
                self.content = TwMapV4.ImageItem(_io__raw_content, self, self._root)
            elif _on == TwMapV4.ItemKind.ex_type_index:
                self._raw_content = self._io.read_bytes(self.data_size)
                _io__raw_content = KaitaiStream(BytesIO(self._raw_content))
                self.content = TwMapV4.ExTypeIndexItem(_io__raw_content, self, self._root)
            elif _on == TwMapV4.ItemKind.envelope:
                self._raw_content = self._io.read_bytes(self.data_size)
                _io__raw_content = KaitaiStream(BytesIO(self._raw_content))
                self.content = TwMapV4.EnvelopeItem(_io__raw_content, self, self._root)
            elif _on == TwMapV4.ItemKind.sound:
                self._raw_content = self._io.read_bytes(self.data_size)
                _io__raw_content = KaitaiStream(BytesIO(self._raw_content))
                self.content = TwMapV4.SoundItem(_io__raw_content, self, self._root)
            elif _on == TwMapV4.ItemKind.group:
                self._raw_content = self._io.read_bytes(self.data_size)
                _io__raw_content = KaitaiStream(BytesIO(self._raw_content))
                self.content = TwMapV4.GroupItem(_io__raw_content, self, self._root)
            else:
                self._raw_content = self._io.read_bytes(self.data_size)
                _io__raw_content = KaitaiStream(BytesIO(self._raw_content))
                self.content = TwMapV4.UnknownItem(_io__raw_content, self, self._root)




