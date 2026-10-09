-- Acquire the writer transaction before checking the existing history.
UPDATE witful_checkpoints SET ordinal = ordinal
WHERE FALSE;
