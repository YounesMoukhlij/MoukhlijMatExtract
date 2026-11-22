# Example: two papers, the whole pipeline

A worked example for trying MoukhlijMatExtract without papers of your own, and for checking that an
installation gives the results it should. It extracts the values of two open-access papers, ranks the
materials and classifies them:

```bash
make demo        # from the source folder; the results go to examples/output/
```

or, step by step, from the source folder:

```bash
mme-local extract -i "$PWD/examples/papers" -o "$PWD/examples/output/database" --offline
mme-rank     --source "$PWD/examples/output/database" --out "$PWD/examples/output/ranking"
mme-classify --source "$PWD/examples/output/database" --out "$PWD/examples/output/classes"
```

The commands work from the project folder `~/MoukhlijMatExtract`, so a relative path is read from there;
`$PWD/` gives the full path of the source folder (in PowerShell too).

It takes about a minute. `--offline` leaves out the OpenAlex lookup of each paper's title, authors and
journal, so the run needs no network and gives the same result on every computer.

## The papers

Both are published under the Creative Commons Attribution 4.0 license (CC BY), which allows them to be
copied and shared with this attribution. They are included unchanged.

| File | Paper | License |
|---|---|---|
| `papers/10.1021_acsomega.8b00377.pdf` | A. Sakuda, A. Yamauchi, S. Yubuchi, N. Kitamura, Y. Idemoto, A. Hayashi, M. Tatsumisago, *Mechanochemically Prepared Li2S–P2S5–LiBH4 Solid Electrolytes with an Argyrodite Structure*, ACS Omega 3, 5453–5458 (2018). [doi:10.1021/acsomega.8b00377](https://doi.org/10.1021/acsomega.8b00377) | [CC BY](https://creativecommons.org/licenses/by/4.0/) |
| `papers/10.1021_acs.chemmater.6b02516.pdf` | R. Wagner, G. J. Redhammer, D. Rettenwander, G. Tippelt, A. Welzl, S. Taibl, J. Fleig, A. Franz, W. Lottermoser, G. Amthauer, *Fast Li-Ion-Conducting Garnet-Related Li7–3xFexLa3Zr2O12 with Uncommon I4̅3d Structure*, Chem. Mater. 28, 5943–5951 (2016). [doi:10.1021/acs.chemmater.6b02516](https://doi.org/10.1021/acs.chemmater.6b02516) | [CC BY](https://creativecommons.org/licenses/by/4.0/) |

## What comes out

`expected_values.csv` lists the activation energies and conductivities this version extracts from the two
papers. The tests (`LocalExtraction/tests/test_demo.py`) extract the papers again and compare.

The list is what the program gives, not a corrected answer: it shows its strengths and its limits on
real papers.

- **Read correctly.** The activation energy of 16 kJ mol⁻¹ (0.166 eV) and the conductivities of 1.8 and
  1.9 mS cm⁻¹ of the x = 50 member of the series (100−x)(0.75Li₂S·0.25P₂S₅)·xLiBH₄. The sentences say
  only "the x = 50 samples"; the program finds the series the paper named pages before, and computes the
  composition of that member.
- **A table without ruling lines.** Table 3 of the garnet paper gives σbulk and Ea for x = 0.18 and 0.25
  of Li₇₋₃ₓFeₓLa₃Zr₂O₁₂; each row is given its own composition, Li₆.₄₆La₃Zr₂Fe₀.₁₈O₁₂ and
  Li₆.₂₅La₃Zr₂Fe₀.₂₅O₁₂.
- **Cited values.** The values of other works quoted in the introductions are marked `cited`, not `this
  work`.
- **Wrong material.** In "The crystalline sample with x = 50 exhibits a higher conductivity (1.8 × 10⁻³
  S cm⁻¹) … than those of the 75Li₂S·25P₂S₅ glass … and the LiBH₄ crystal", the value goes to LiBH₄,
  the formula nearest to it, not to the x = 50 sample. In the garnet paper, "the activation energy is
  ∼0.29 eV for the samples" (page 6) goes to Li₇La₃Zr₂O₁₂ (LLZO), the parent compound the paper names,
  not to the Fe-substituted samples. See [docs/LIMITATIONS.md](../../docs/LIMITATIONS.md).
