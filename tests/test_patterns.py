from what2_regex import w2


def test_ch_set():
    ch_set = "[abc]"
    ch_xset = "[^abc]"

    w2_ch_set = w2.ch_set("abc")
    assert w2_ch_set == ch_set
    assert ~w2_ch_set == ch_xset


def test_or():
    or_seq = "abc|def|ghi"
    w2_or_seq = w2.or_seq("abc", "def", "ghi")
    assert str(w2_or_seq) == or_seq
    cg_repeating_or_seq = "(abc|def|ghi)*"
    w2_cg_repeating_or_seq = w2.cg(w2_or_seq).repeat

    assert cg_repeating_or_seq == w2_cg_repeating_or_seq


def test_esc_set():
    pat = w2.ch_set.esc("a-z").c()

    assert pat.match("b") is None
