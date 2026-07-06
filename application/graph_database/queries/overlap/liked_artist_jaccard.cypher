// Overlap pack (plan 06 T9): Jaccard similarity over the two users'
// liked-artist sets — one number for "how alike are our tastes".
//
//   J(A, B) = |A ∩ B| / |A ∪ B|
//
// where A/B are the sets of artists with a CREATED credit on at least one
// track the user liked. 0.0 = disjoint tastes, 1.0 = identical. Jaccard is
// deliberately size-normalized: a 12k-track library vs a 300-track library
// still yields an honest similarity (raw intersection counts would not).
//
// Documented query pack (not executed by the pipeline). Requires migration
// 0001. OPTIONAL MATCH + coalesce keep the row well-defined (0.0) even when a
// user has no likes at all.
//
// Params: $a, $b
OPTIONAL MATCH (:User {id: $a})-[:LIKED]->(:Track)<-[:CREATED]-(ar_a:Artist)
WITH collect(DISTINCT ar_a) AS a_set
OPTIONAL MATCH (:User {id: $b})-[:LIKED]->(:Track)<-[:CREATED]-(ar_b:Artist)
WITH a_set, collect(DISTINCT ar_b) AS b_set
WITH a_set, b_set,
     size([artist IN a_set WHERE artist IN b_set]) AS intersection_size
WITH size(a_set) AS a_artists,
     size(b_set) AS b_artists,
     intersection_size,
     size(a_set) + size(b_set) - intersection_size AS union_size
RETURN a_artists,
       b_artists,
       intersection_size,
       union_size,
       CASE WHEN union_size = 0 THEN 0.0
            ELSE toFloat(intersection_size) / union_size
       END AS jaccard
;
