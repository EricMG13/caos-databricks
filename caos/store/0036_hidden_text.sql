-- N27: why a line of a PDF may not be seen on the rendered page -- drawn in
-- text render mode 3 (every OCR'd scan's text layer), painted near the colour
-- behind it, or in glyphs under 2 pt. The text stays evidence and citable; its
-- tokens and blocks carry the line's reasons, sorted and joined by a comma,
-- so the page read can show the approver and the prompt can tell the model.
-- NULL is a line with nothing to note, and every row written before this
-- migration. A source carrying a mark is written as output format 2, whose
-- digest includes the mark; nothing already stored changes.
ALTER TABLE source_tokens ADD COLUMN hidden text
    CONSTRAINT source_tokens_hidden_check CHECK (hidden IN (
        'near_background', 'near_background,render_mode_3',
        'near_background,render_mode_3,under_2pt', 'near_background,under_2pt',
        'render_mode_3', 'render_mode_3,under_2pt', 'under_2pt'
    ));
ALTER TABLE source_blocks ADD COLUMN hidden text
    CONSTRAINT source_blocks_hidden_check CHECK (hidden IN (
        'near_background', 'near_background,render_mode_3',
        'near_background,render_mode_3,under_2pt', 'near_background,under_2pt',
        'render_mode_3', 'render_mode_3,under_2pt', 'under_2pt'
    ));
