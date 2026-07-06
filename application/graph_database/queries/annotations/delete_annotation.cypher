// Undo for Notes and Cues (Sections use delete_section_and_reopen_previous,
// which also repairs the NEXT chain's end_ms bookkeeping).
MATCH (a)
WHERE a.id = $annotation_id AND (a:Note OR a:Cue)
DETACH DELETE a
;
