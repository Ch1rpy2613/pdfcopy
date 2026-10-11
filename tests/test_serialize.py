from pdfcopy.serialize import _join_soft_break, is_cjk


def test_cjk_detection():
    assert is_cjk("中")
    assert is_cjk("。")
    assert not is_cjk("A")


def test_hyphen_join():
    assert _join_soft_break("inter-", "national") == "international"


def test_cjk_join_has_no_space():
    assert _join_soft_break("你好", "世界") == "你好世界"


def test_mixed_script_line_wrap_stays_tight():
    # Soft wraps must not invent a space; same-line gaps still do.
    assert _join_soft_break("使用", "PDF") == "使用PDF"
    assert _join_soft_break("PDF", "文件") == "PDF文件"
