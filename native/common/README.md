# Native Common

Owns shared native helper headers used by native subprojects.

Keep this area small and generic. Put helper-specific code in the owning native
package, not in shared headers, unless more than one native target uses it now.

Related docs: native helper package READMEs and `docs/project-map.md`.
Related tests: native build, runtime smoke, and packaging entries in
`docs/test-matrix.md`.
