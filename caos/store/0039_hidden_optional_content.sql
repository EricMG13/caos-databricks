-- N27's remainder: a line of a PDF drawn inside optional content the
-- document's default configuration switches off is marked
-- `optional_content_off`, beside 0036's three reasons. The checks are widened
-- to every sorted combination of the four; every row already stored holds one
-- of 0036's seven, which stay, and nothing stored changes.
ALTER TABLE source_tokens DROP CONSTRAINT source_tokens_hidden_check;
ALTER TABLE source_tokens ADD CONSTRAINT source_tokens_hidden_check
    CHECK (hidden IN (
        'near_background', 'near_background,optional_content_off',
        'near_background,optional_content_off,render_mode_3',
        'near_background,optional_content_off,render_mode_3,under_2pt',
        'near_background,optional_content_off,under_2pt',
        'near_background,render_mode_3', 'near_background,render_mode_3,under_2pt',
        'near_background,under_2pt', 'optional_content_off',
        'optional_content_off,render_mode_3',
        'optional_content_off,render_mode_3,under_2pt',
        'optional_content_off,under_2pt', 'render_mode_3', 'render_mode_3,under_2pt',
        'under_2pt'
    ));
ALTER TABLE source_blocks DROP CONSTRAINT source_blocks_hidden_check;
ALTER TABLE source_blocks ADD CONSTRAINT source_blocks_hidden_check
    CHECK (hidden IN (
        'near_background', 'near_background,optional_content_off',
        'near_background,optional_content_off,render_mode_3',
        'near_background,optional_content_off,render_mode_3,under_2pt',
        'near_background,optional_content_off,under_2pt',
        'near_background,render_mode_3', 'near_background,render_mode_3,under_2pt',
        'near_background,under_2pt', 'optional_content_off',
        'optional_content_off,render_mode_3',
        'optional_content_off,render_mode_3,under_2pt',
        'optional_content_off,under_2pt', 'render_mode_3', 'render_mode_3,under_2pt',
        'under_2pt'
    ));
