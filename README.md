# What2 RegEx

A library to help composing Regular Expressions.
Designed for readability, not speed. Directly
compiling the equivalent string literal would
be faster but probably harder to read.

If you're not the author I probably don't recommend
using this, but I also don't recommend using regular
expressions so needs must.

Class names are intentionally shorthand so they're
using snake case function-like names to improve
readability.

## Examples

A regular expression to match a file protocol
could be

```
(git\\+)?(git|ssh|https?|file)://
```

This is a fairly simple regular expression, but
it's not the easiest thing to read. Using this
library instead you can write

```python
from what2_regex import w2

protocol = w2.seq(
    w2.cg(
        "git",
        w2.ch.esc("+"),
    ).optional,
    w2.or_cg(
        "git",
        "ssh",
        w2.seq("http", w2.ch("s").optional,
        "file",
    ),
    "://",
)
```

Which _I_ think is easier to read.

The expression can be converted to a string
or printed directly
```python
>>> print(protocol)
(git\+)?(git|ssh|https?|file)://
```
or compiled
```python
protocol.c()
```

But what about something more complex?
How about the [grapheme clustering rules](https://unicode.org/reports/tr29/#Regex_Definitions)
```python
cr_lf = w2.seq(CR, LF)
any_ctl = w2.ch_set(CR, LF, Control)
non_ctl = ~any_ctl

hangul_inner = w2.seq(
    w2.ch(L).repeat,
    w2.or_g(
        w2.ch(V).req_repeat,
        w2.seq(LV, w2.ch(V).repeat),
        LVT,
    ),
    w2.ch(T).repeat,
)

hangul = w2.or_seq(
    hangul_inner,
    w2.ch(L).req_repeat,
    w2.ch(T).req_repeat,
)

ri_ri = w2.seq(Regional_Indicator, Regional_Indicator)
xpicto = w2.seq(
    Extended_Pictographic,
    w2.g(
        w2.ch(Extend).repeat,
        ZWJ,
        Extended_Pictographic,
    ).repeat,
)

incb = w2.seq(
    InCB_Consonant,
    w2.g(
        w2.ch_set(
            Extend,
            ZWJ,
        ).repeat,
        InCB_Linker,
        w2.ch_set(
            Extend,
            InCB_Linker,
            ZWJ,
        ).repeat,
        InCB_Consonant,
    ).req_repeat,
)

pre_core = w2.ch(Prepend)
core = w2.or_g(
    hangul,
    ri_ri,
    xpicto,
    incb,
    non_ctl,
)

post_core = w2.ch_set(
    Extend,
    ZWJ,
    SpacingMark,
    InCB_Linker,
)

op_egc_re = w2.or_seq(
    cr_lf,
    any_ctl,
    w2.seq(
        pre_core.repeat,
        core,
        post_core.repeat,
    ),
)
```

Swapping single characters a-q for each character class, this is:
```
ab|[abc]|i*(?:d*(?:e+|fe*|h)g*|d+|ll|k(?:n*pk)*|j(?:[nqp]*?q[nqp]*j)*|[^abc])[npoq]*
```
The above regex is borderline incomprehensible,
and why I wrote this.
