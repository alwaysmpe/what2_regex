"""
RegEx component classes.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator
import contextlib
from dataclasses import dataclass
from inspect import getdoc
import re
from typing import LiteralString, TypeAlias, Unpack, cast, final, overload, override

type _Tp[*Args] = tuple[*Args]

# Unused forward ref to or_seq, causes error without below.
# "As designed" - https://github.com/microsoft/pyright/issues/9641
# "Circular types" aren't supported (they're just part of the type system)...
type _OrSeqT = or_seq # noqa: PYI047
type _ReComposableVT = str | ReComposable
_ReComposableT: TypeAlias = tuple[_ReComposableVT, ...] # noqa: UP040 - runtime error... https://github.com/python/cpython/issues/126085
type _ReOrVT = ReExpr | ReTokenExpr | str | ch_set | ch_xset | or_seq
type _ReOrT = tuple[_ReOrVT, _ReOrVT, *tuple[_ReOrVT, ...]]


def unpack(exprs: Re | str | tuple[Re | str, ...]) -> Iterator[str]:
    """
    Unpack a nested RegEx to a sequence of raw string components.

    :param exprs:   The nested expression to unpack.
    :yields:        The raw string components.
    """
    match exprs:
        case str():
            yield exprs
        case Re():
            yield from exprs
        case tuple():
            for expr in exprs:
                yield from unpack(expr)


@final
class GroupingRedundance(TypeError):
    """
    Single character grouping is possibly
    redundant - use a ch, seq or plain str
    instance instead.
    """ # noqa: D205

    def __init__(self, *args: object) -> None:
        docstring = getdoc(self)
        assert docstring is not None
        message = docstring.replace("\n", " ")
        super().__init__(message, *args)


class Re(ABC, Iterable[str]):
    """
    Base RegEx pattern.
    """

    @override
    def __str__(self) -> str:
        return "".join(self)

    @property
    @abstractmethod
    def _inner(self) -> Iterator[str | Re]:
        ...

    @property
    @abstractmethod
    def _raw_seq(self) -> str:
        ...

    @property
    def raw(self) -> str:
        """
        The raw RegEx string.
        """
        return str(self)

    def check_redundance(self, parent: Re | None = None) -> None: # type: ignore[reportUnusedParameter] # noqa: ARG002
        """
        Raise an exception if there is (detected) redundance in the expression.

        EG `(?:abc)` is equivalent to `abc`.
        """
        for child in self._inner:
            if isinstance(child, Re):
                child.check_redundance(self)

    @override
    def __eq__(self, value: object) -> bool:
        match value:
            case Re():
                return str(self) == str(value)
            case str():
                return str(self) == value
            case _:
                return False


class ReCompilable(Re, ABC):
    """
    A compilable expression.

    Some expressions, while they are syntactically compilable
    are redundant to compile. For example the expression::

        A|B

    is equivalent to::

        (?:A|B)

    but the grouping in the latter is redundant so typed to not be
    compilable to discourage redundancy.
    """

    def c(self) -> re.Pattern[str]:
        """
        Compile to a regex pattern.
        """
        return re.compile(self.raw)

    def bc(self) -> re.Pattern[bytes]:
        """
        Compile to a byte regex pattern.
        """
        return re.compile(self.raw.encode())


class ReComposable(Re, ABC):
    """
    A regular expression that can be composed with other expressions without changing intended meaning.

    For example a group or character set is composable. Starting with the expression::

        [Hh]

    which would match `H` or `h` is likely to behave as intended if composed. For example
    composing it with addtiional character matches:

        [Hh]ello

    would match either `Hello` or `hello`. This is likely what's intended.
    Whereas an or sequence::

        H|h

    which would also match `H` or `h` is unlikely to behave as intended if composed::

        H|hello

    This now matches `H` or `hello`, unlikely to be what was intended.
    Therefore unextendable expressions like an undelimited sequence of
    or's should not derive from this.
    """

    def __add__(self, other: ReComposable) -> seq:
        """
        Combine two delimited regex tokens into a longer sequence.
        """
        return seq(self, other)


class ReExpr(ReCompilable, ReComposable, ABC):
    """
    An undelimited regex expression.

    Meaning should not change if other expressions are appended
    but for example count modifiers would not apply to the entire
    expression.
    """


@dataclass(frozen=True, init=False, eq=False)
class Sequence[SequenceT: tuple[Re | str, ...]](Re, ABC):
    """
    A sequence of values.
    """

    type SeqT = SequenceT

    sequence: SeqT

    def __init__(self, *exprs: Unpack[SeqT]) -> None:
        object.__setattr__(self, "sequence", exprs)

    @property
    @override
    def _raw_seq(self) -> str:
        return "".join(unpack(self))

    @property
    @override
    def _inner(self) -> Iterator[str | Re]:
        yield from self.sequence


@dataclass(frozen=True, init=False, eq=False)
class NestSequence[SequenceT: tuple[Re | str, ...], NestT: Re](Re, ABC):
    """
    A sequence of values or nested expression.
    """

    type SeqT = SequenceT | tuple[NestT]
    type _SequenceT = SequenceT
    type _NestT = tuple[NestT]
    sequence: SeqT

    @overload
    def __init__(self, *exprs: Unpack[SequenceT]) -> None:
        ...

    @overload
    def __init__(self, *exprs: *tuple[NestT]) -> None:
        ...

    def __init__(self, *exprs: Re | str) -> None:
        object.__setattr__(self, "sequence", exprs)

    @property
    @override
    def _raw_seq(self) -> str:
        return "".join(unpack(self))

    @property
    @override
    def _inner(self) -> Iterator[str | Re]:
        yield from self.sequence


@final
@dataclass(frozen=True, init=False, eq=False)
class seq(ReExpr, Sequence[tuple[_ReComposableVT, *_ReComposableT]]):
    """
    Simple matching sequence, potentially composed of other expressions.
    """

    @override
    def __iter__(self) -> Iterator[str]:
        yield from unpack(self.sequence)


class ReAltCh(Re, ABC):
    """
    A simplifiable class.

    A base class indicating that for single characters
    a string, seq or ch class would be a simpler
    alternative.
    """

    @override
    def check_redundance(self, parent: Re | None = None) -> None:
        raw_inner = self._raw_seq
        if len(raw_inner) <= 1:
            raise GroupingRedundance
        return super().check_redundance(parent)


class ReToken(ReComposable, ABC):
    """
    A delimited regex expression.

    Meaning does not change if other expressions are appended.
    Count modifiers can either validly be applied to the entire
    expression or already have been applied.
    """


class ReTokenExpr(ReToken, ReCompilable, ABC):
    """
    A delimited regex expression that can be compiled without explicit redundancy.

    Meaning does not change if other expressions are appended.
    Count modifiers can either validly be applied to the entire
    expression or already have been applied.

    For example, a character set `[abc]` when compiled does not
    contain explicit redundancy, but a capture group does - `(abc)`
    is equivalent to `abc`.
    """


class ReCountable(ReToken, ABC):
    """
    A delimited regex Token expression that can have count modifiers applied to it.

    A single character is implicitly delimited. Other examples are a group or set of characters.

    While counts could be implemented with multiply and slicing operators, this would be
    less explicit and defeat the point.
    """

    @property
    def optional(self) -> _counted:
        """
        Optionally match the current token.
        """
        return _counted(self, "?")

    def count(self, count: int) -> _counted:
        """
        Match the current token exactly count times.
        """
        # assert count > 0
        return _counted(self, f"{{{count}}}")

    @overload
    def counts(self, min_count: int, max_count: int) -> _counted:
        ...

    @overload
    def counts(self, *, min_count: int, max_count: None = None) -> _counted:
        ...

    @overload
    def counts(self, *, max_count: int, min_count: None = None) -> _counted:
        ...

    def counts(self, min_count: int | None = None, max_count: int | None = None) -> _counted:
        """
        Match the current token between min_count and max_count times, inclusive.
        """
        if (min_count is not None) and (max_count is not None):
            assert max_count > min_count >= 0
            return _counted(self, f"{{{min_count},{max_count}}}")

        if min_count is not None:
            return _counted(self, f"{{{min_count},}}")

        if max_count is not None:
            return _counted(self, f"{{,{max_count}}}")

        raise ValueError

    @property
    def repeat(self) -> _counted:
        """
        The current token, repeated zero or more times.
        """
        return _counted(self, "*")

    @property
    def ng_repeat(self) -> _counted:
        """
        The current token, repeated zero or more times, non-greedy.
        """
        return _counted(self, "*?")

    @property
    def req_repeat(self) -> _counted:
        """
        The current token, repeated one or more times.
        """
        return _counted(self, "+")

    @property
    def ng_req_repeat(self) -> _counted:
        """
        The current token, repeated one or more times, non-greedy.
        """
        return _counted(self, "+?")


@dataclass(frozen=True, init=False, eq=False)
@final
class _counted(
        ReTokenExpr,
        Sequence[tuple[ReCountable, str]],
):
    @override
    def check_redundance(self, parent: Re | None = None) -> None:
        expr = self.sequence[0]

        # if the immediately nested expression
        # is a group it isn't redundant.
        with contextlib.suppress(GroupingRedundance):
            expr.check_redundance()

        # groupings are not necessarily redundant if there is
        # a count modifier applied, so some redundance checks
        # may not apply. ReAltCh counted sequences can (probably)
        # be replaced with a ch if they're a single character pattern.
        raw_expr = expr._raw_seq # noqa: SLF001

        if isinstance(expr, ReAltCh) and (len(raw_expr) == 1):
            message = f"Count modifiers can be applied to single characters. Character sequence: {raw_expr}"
            raise GroupingRedundance(message)

        for inner_expr in expr._inner: # noqa: SLF001
            if isinstance(inner_expr, Re):
                inner_expr.check_redundance(expr)

    @override
    def __iter__(self) -> Iterator[str]:
        yield from self.sequence[0]
        yield self.sequence[1]


@dataclass(frozen=True, init=False, eq=False)
class ch(ReCountable, ReTokenExpr, Sequence[tuple[str]]):
    """
    A single character regex token.

    Must be a single character.
    """

    class esc(ReCountable, ReTokenExpr, Sequence[tuple[str]]):
        """
        A single character regex token that is escaped.
        """

        def __or__(self, value: ch_set.esc | ch.esc) -> ch_set.esc:
            """
            Combine this character with another character or character set.
            """
            return ch_set.esc(*self.sequence, *value.sequence)

        def __post_init__(self) -> None:
            """
            Post init to validate values.
            """
            if len(self.sequence[0]) != 1:
                raise ValueError

        @override
        def __iter__(self) -> Iterator[str]:
            yield re.escape(self.sequence[0])

        def __invert__(self) -> ch_xset.esc:
            """
            Invert to match everything except this escaped character (the compliment of this character).
            """
            return ch_xset.esc(self.sequence[0])

    def __post_init__(self) -> None:
        """
        Post init to validate values.
        """
        if len(self.sequence[0]) != 1:
            raise ValueError

    def __or__(self, value: ch_set | ch) -> ch_set:
        """
        Combine this character with another character or character set.
        """
        return ch_set(*self.sequence, *value.sequence)

    @override
    def __iter__(self) -> Iterator[str]:
        yield self.sequence[0]

    def __invert__(self) -> ch_xset:
        """
        Invert to match everything except this character (the compliment of this character).
        """
        return ch_xset(self.sequence[0])


@final
@dataclass(frozen=True, init=False, eq=False)
class lit_seq[T: LiteralString](ReExpr, Sequence[_Tp[T]]):
    """
    Literal expression.
    """

    @override
    def __iter__(self) -> Iterator[T]:
        yield self.sequence[0]

    @final
    @dataclass(frozen=True, init=False, eq=False)
    class esc(ReExpr, Sequence[_Tp[str, *tuple[str, ...]]]):
        """
        Escaped literal expression.
        """

        @override
        def __iter__(self) -> Iterator[str]:
            for expr in unpack(self.sequence):
                yield re.escape(expr)


@final
@dataclass(frozen=True, init=False, eq=False)
class or_seq(ReCompilable, Sequence[_ReOrT]):
    r"""
    RegEx 'or' of each passed expression in a non-capture group.

    From the docs:
        `|`
            `A|B`, where A and B can be arbitrary REs, creates
            a regular expression that will match either A or
            B. An arbitrary number of REs can be separated by
            the `|` in this way. This can be used inside groups
            (see below) as well. As the target string is scanned,
            REs separated by `|` are tried from left to right.
            When one pattern completely matches, that branch is
            accepted. This means that once A matches, B will not
            be tested further, even if it would produce a longer
            overall match. In other words, the `|` operator is
            never greedy. To match a literal `|`, use \|, or
            enclose it inside a character class, as in [|].
    """

    @override
    def __iter__(self) -> Iterator[str]:
        it = iter(self.sequence)
        yield from unpack(next(it))
        for expr in it:
            yield "|"
            yield from unpack(expr)


class ReGroup(ReToken, ABC):
    """
    A regex grouping expression.

    For example a char set or capture group.
    Explicitly delimited.
    """


class ReCountableGroup(ReGroup, ReCountable, ABC):
    """
    A regex grouping expression that can have counting modifiers applied.

    For example a char set or capture group, explicitly delimited.

    Some negative matchers have unexpected behaviour
    with count expressions so may not allow count modifiers.
    For example character set compliments work intuitively:

        [^abc]{2}

    will match:

        de

    however:

        foo(?!bar){2}

    is somewhat redundant as it has effectively equivalent
    behaviour to the uncounted expression `foo(?!bar)`.
    """


@final
@dataclass(frozen=True, init=False, eq=False)
class ch_set(ReCountableGroup, ReTokenExpr, ReAltCh, Sequence[_Tp[str, *tuple[str, ...]]]):
    """
    A set of characters to match.

    Expressions are not escaped, so ranges of characters
    can still be used. For example `ch_set("a-z")` will
    match any lowercase ASCII letter and is equivalent
    to the regex expression "[a-z]".
    """

    @final
    @dataclass(frozen=True, init=False, eq=False)
    class esc(ReCountableGroup, ReTokenExpr, ReAltCh, Sequence[_Tp[str, *tuple[str, ...]]]):
        """
        A set of escaped characters to match.

        Ranges are implicitly not supported as the range `-` character would be escaped.
        """

        def __or__(self, value: ch_set.esc | ch.esc) -> ch_set.esc:
            """
            Combine this escaped character set with another character or character set.
            """
            return ch_set.esc(*self.sequence, *value.sequence)

        def __invert__(self) -> ch_xset.esc:
            """
            Invert to a non-matching escaped character set (the compliment of this set).
            """
            return ch_xset.esc(*self.sequence)

        @override
        def __iter__(self) -> Iterator[str]:
            yield "["
            for chars in unpack(self.sequence):
                yield re.escape(chars)
            yield "]"

    def __or__(self, value: ch_set | ch) -> ch_set:
        """
        Combine this character set with another character or character set.
        """
        return ch_set(*self.sequence, *value.sequence)

    def __invert__(self) -> ch_xset:
        """
        Invert to a non-matching character set (the compliment of this set).
        """
        return ch_xset(*self.sequence)

    @override
    def __iter__(self) -> Iterator[str]:
        yield "["
        yield from unpack(self.sequence)
        yield "]"


@final
@dataclass(frozen=True, init=False, eq=False)
class ch_xset(ReCountableGroup, ReTokenExpr, Sequence[_Tp[str, *tuple[str, ...]]]):
    """
    A set of characters not to match.

    Expressions are not escaped, so ranges of characters
    can still be used. For example `ch_xset("a-z")` will
    match anything except any lowercase ASCII letter and
    is equivalent to the regex expression "[^a-z]".
    """

    @final
    @dataclass(frozen=True, init=False, eq=False)
    class esc(ReCountableGroup, ReTokenExpr, Sequence[_Tp[str, *tuple[str, ...]]]):
        """
        A set of escaped characters not to match.

        Ranges are implicitly not supported as the range character would be escaped.
        """

        def __invert__(self) -> ch_set.esc:
            """
            Invert to a matching escaped character set (the compliment of this set).
            """
            return ch_set.esc(*self.sequence)

        @override
        def __iter__(self) -> Iterator[str]:
            yield "[^"
            for chars in unpack(self.sequence):
                yield re.escape(chars)
            yield "]"

    def __invert__(self) -> ch_set:
        """
        Invert to a matching character set (the compliment of this set).
        """
        return ch_set(*self.sequence)

    @override
    def __iter__(self) -> Iterator[str]:
        yield "[^"
        yield from unpack(self.sequence)
        yield "]"


@final
@dataclass(frozen=True, init=False, eq=False)
class g(ReCountableGroup, ReAltCh, NestSequence[_Tp[_ReComposableVT, *_ReComposableT], or_seq | seq]):
    """
    Non-capturing group.

    From the docs:

        `(?:...)`
            A non-capturing version of regular parentheses. Matches
            whatever regular expression is inside the parentheses,
            but the substring matched by the group cannot be retrieved
            after performing a match or referenced later in the pattern.
    """

    def __invert__(self) -> ng:
        """
        Invert to a non-matching lookahead group.
        """
        # A typed sequence doesn't preserve typing when unpacked...
        if len(self.sequence) == 1:
            return ng(self.sequence[0])
        else:
            return ng(*self.sequence)

    @override
    def check_redundance(self, parent: Re | None = None) -> None:
        # combining conditionals messes with type narrowing
        raw = self._raw_seq
        if raw == re.escape(raw): # noqa: SIM102 # un nesting ifs messes with type checking.
            if isinstance(parent, _counted):
                message = f"Group does not seem to be grouping any special characters and has no count modifiers applied. Grouped expression: {raw}"
                raise GroupingRedundance(message)

        redundant_parent_types = or_g, or_seq, g
        if isinstance(parent, redundant_parent_types):
            message = f"Group nested in {parent.__class__.__name__} possibly redundant."
            raise GroupingRedundance(message)

        return super().check_redundance(parent)

    @override
    def __iter__(self) -> Iterator[str]:
        yield "(?:"
        yield from unpack(self.sequence)
        yield ")"


@final
@dataclass(frozen=True, init=False, eq=False)
class ng(ReGroup, NestSequence[_Tp[_ReComposableVT, *_ReComposableT], or_seq | seq]):
    """
    Non-matching lookahead group.

    From the docs:
        `(?!...)`
            Matches if ... doesn't match next. This
            is a negative lookahead assertion. For
            example, Isaac (?!Asimov) will match
            'Isaac ' only if it's not followed by
            'Asimov'.
    """

    def __invert__(self) -> g:
        """
        Invert to a matching non-capturing group.
        """
        # unpacking isn't typed...
        if len(self.sequence) == 1:
            return g(self.sequence[0])
        else:
            return g(*self.sequence)

    @override
    def __iter__(self) -> Iterator[str]:
        yield "(?!"
        yield from unpack(self.sequence)
        yield ")"


@final
@dataclass(frozen=True, init=False, eq=False)
class np(ReGroup, NestSequence[_Tp[_ReComposableVT, *_ReComposableT], or_seq | seq]):
    """
    "Negative lookbehind assertion" - not preceeded by.

    From the docs:

        `(?<!...)`
            Matches if the current position in the string is not
            preceded by a match for .... This is called a negative
            lookbehind assertion. Similar to positive lookbehind
            assertions, the contained pattern must only match strings
            of some fixed length. Patterns which start with negative
            lookbehind assertions may match at the beginning of the
            string being searched.
    """

    @override
    def __iter__(self) -> Iterator[str]:
        yield "(?<!"
        yield from unpack(self.sequence)
        yield ")"


@final
@dataclass(frozen=True, init=False, eq=False)
class cg(ReCountableGroup, NestSequence[_Tp[_ReComposableVT, *_ReComposableT], or_seq | seq]):
    r"""
    Capturing group.

    From the docs:
        `(...)`
            Matches whatever regular expression is inside
            the parentheses, and indicates the start and
            end of a group; the contents of a group can
            be retrieved after a match has been performed,
            and can be matched later in the string with the
            \number special sequence, described below. To
            match the literals '(' or ')', use \( or \),
            or enclose them inside a character class:
            [(], [)].
    """

    @override
    def __iter__(self) -> Iterator[str]:
        yield "("
        yield from unpack(self.sequence)
        yield ")"


@final
@dataclass(frozen=True, init=False, eq=False)
class n_cg(ReCountableGroup, NestSequence[_Tp[_ReComposableVT, *_ReComposableT], or_seq | seq]):
    """
    Named capturing group.

    From the docs:
        `(?P<name>...)`
            Similar to regular parentheses, but the substring
            matched by the group is accessible via the symbolic
            group name name. Group names must be valid Python
            identifiers, and in bytes patterns they can only
            contain bytes in the ASCII range. Each group name
            must be defined only once within a regular expression.
            A symbolic group is also a numbered group, just as
            if the group were not named.
    """

    @final
    @dataclass(frozen=True, init=False, eq=False)
    class _nr(ReCountableGroup, Sequence[_Tp[str]]):
        """
        Reference to named group.
        """

        @override
        def __iter__(self) -> Iterator[str]:
            yield f"(?P={self.sequence[0]})"

    name: str

    @overload
    def __init__(self, name: str, *exprs: *tuple[or_seq | seq]) -> None:
        ...

    @overload
    def __init__(self, name: str, *exprs: *tuple[_ReComposableVT, *_ReComposableT]) -> None:
        ...

    def __init__(self, name: str, *exprs: *tuple[or_seq | seq | _ReComposableVT, ...]) -> None:
        object.__setattr__(self, "name", name)
        # TODO: simplify?
        exprs = cast("n_cg.SeqT", exprs)
        if len(exprs) > 1:
            super().__init__(*exprs)
        else:
            val = exprs[0]
            if isinstance(val, or_seq | seq):
                super().__init__(val)
            else:
                super().__init__(val)

    @override
    def __iter__(self) -> Iterator[str]:
        yield f"(?P<{self.name}>"
        yield from unpack(self.sequence)
        yield ")"

    @property
    def ref(self) -> _nr:
        """
        A regex token referencing this named group.
        """
        return self._nr(self.name)


@final
@dataclass(frozen=True, init=False, eq=False)
class or_g(ReCountableGroup, Sequence[_ReOrT]):
    """
    RegEx 'or' of each passed expression in a non-capture group.

    See `or_seq` and `g` for the respective documentation.
    """

    @override
    def check_redundance(self, parent: Re | None = None) -> None:
        is_char_set = all(isinstance(child, str) and (len(child) == 1) for child in self.sequence)
        if is_char_set:
            message = f"or group of characters could be replaced by a character set. Characters being or'd: {self._raw_seq}"
            raise TypeError(message)

        for child in self.sequence:
            if isinstance(child, Re):
                child.check_redundance(self)

    @override
    def __iter__(self) -> Iterator[str]:
        it = iter(self.sequence)
        yield "(?:"
        yield from unpack(next(it))
        for expr in it:
            yield "|"
            yield from unpack(expr)
        yield ")"

    def __invert__(self) -> ng:
        """
        Convert to a non-matching pattern.

        This is done by wrapping the enclosed
        `or_seq` in a non-matching lookahead
        group.

        :returns: The compliment.
        """
        return ng(or_seq(*self.sequence))


@final
@dataclass(frozen=True, init=False, eq=False)
class or_cg(ReCountableGroup, Sequence[_ReOrT]):
    """
    RegEx 'or' of each passed expression in a capture group.

    See `or_seq` and `cg` for the respective documentation.
    """

    @override
    def __iter__(self) -> Iterator[str]:
        it = iter(self.sequence)
        yield "("
        yield from unpack(next(it))
        for expr in it:
            yield "|"
            yield from unpack(expr)
        yield ")"


@final
@dataclass(frozen=True, init=False, eq=False)
class ag(ReTokenExpr, ReCountable, NestSequence[_Tp[_ReComposableVT, *_ReComposableT], or_seq | seq]):
    """
    Atomic group match.

    From the docs:
        `(?>...)`
            Attempts to match ... as if it was a separate
            regular expression, and if successful, continues
            to match the rest of the pattern following it.
            If the subsequent pattern fails to match, the
            stack can only be unwound to a point before the
            (?>...) because once exited, the expression,
            known as an atomic group, has thrown away all
            stack points within itself. Thus, (?>.*).
            would never match anything because first the
            .* would match all characters possible, then,
            having nothing left to match, the final . would
            fail to match. Since there are no stack points
            saved in the Atomic Group, and there is no
            stack point before it, the entire expression
            would thus fail to match.
    """

    @override
    def __iter__(self) -> Iterator[str]:
        yield "(?>"
        yield from unpack(self.sequence)
        yield ")"


alpha = ch_set("a-zA-Z")
"""
Latin alphabet characters.
"""
num = ch_set("0-9")
"""
Arabic numerals.
"""
line_end = g("$")
line_start = g("^")
str_start = g("\\A")
