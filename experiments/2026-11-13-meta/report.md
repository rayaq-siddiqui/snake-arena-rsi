# RSI run: meta: GaussianHillClimb settings on toy quadratics

- proposer: `gaussian_hill_climb`; rule: `PairedBootstrapRule` (min gain 2%, 10,000 bootstrap resamples)
- run seed 0; framework v1, code 0c04dc7e0c42b233
- generations: 40; accepted: 2; stopped by: generation budget
- episodes used: 4,080

## Final check (champion vs generation-0 baseline on the final seeds)

Mean score -4.506 vs -4.746 over 60 seeds: difference +0.2397, 95% CI [-0.2332, +0.8064], 0 failures.

## Champion parameters

| parameter | baseline | champion |
|---|---|---|
| sigma | 0.15 | 0.1475 |
| grow | 1.5 | 1.472 |
| shrink | 0.9 | 0.9021 |

## Decisions

| gen | candidate | stage | dev diff | holdout diff | holdout CI | accepted | why |
|---|---|---|---|---|---|---|---|
| 1 | d5d95712 | holdout | +0.3947 | +0.1506 | [-0.37, +0.686] | no | holdout gain +3.5%, 95% CI [-0.3696, +0.6862]: interval reaches 0 |
| 2 | d3c0b38a | dev | -0.5185 | - | - | no | dev mean difference -0.5185 is not above 0 |
| 3 | 1638b3ac | dev | -1.745 | - | - | no | dev mean difference -1.745 is not above 0 |
| 4 | be397019 | holdout | +0.1724 | +0.02377 | [-0.864, +0.847] | no | holdout gain +0.6%, 95% CI [-0.8636, +0.8465]: below the 2% minimum gain |
| 5 | beed1438 | holdout | +0.8778 | +0.04856 | [-0.505, +0.619] | no | holdout gain +1.1%, 95% CI [-0.5052, +0.6191]: below the 2% minimum gain |
| 6 | 9d801e2a | dev | -0.002659 | - | - | no | dev mean difference -0.002659 is not above 0 |
| 7 | 2767aed3 | dev | -0.4272 | - | - | no | dev mean difference -0.4272 is not above 0 |
| 8 | 720f02c2 | dev | -0.8992 | - | - | no | dev mean difference -0.8992 is not above 0 |
| 9 | c3c36c39 | holdout | +0.2357 | -0.008978 | [-0.857, +0.866] | no | holdout gain -0.2%, 95% CI [-0.857, +0.866]: below the 2% minimum gain |
| 10 | 3e281e80 | holdout | +0.2757 | +0.01619 | [-0.814, +0.728] | no | holdout gain +0.4%, 95% CI [-0.8137, +0.728]: below the 2% minimum gain |
| 11 | 041c0377 | holdout | +0.5208 | -0.5968 | [-1.6, +0.338] | no | holdout gain -12.6%, 95% CI [-1.601, +0.3382]: below the 2% minimum gain |
| 12 | aaccc4d2 | dev | -0.637 | - | - | no | dev mean difference -0.637 is not above 0 |
| 13 | 289113f1 | dev | -0.724 | - | - | no | dev mean difference -0.724 is not above 0 |
| 14 | c0d856c5 | dev | -0.1423 | - | - | no | dev mean difference -0.1423 is not above 0 |
| 15 | 3c75f729 | holdout | +0.2872 | +0.08639 | [-0.481, +0.719] | no | holdout gain +1.9%, 95% CI [-0.4814, +0.7189]: below the 2% minimum gain |
| 16 | 1cec3f95 | holdout | +0.2136 | +0.3916 | [+0.036, +0.873] | yes | accepted: holdout gain +8.8%, 95% CI [+0.03596, +0.8733] |
| 17 | 88706a43 | dev | -0.1691 | - | - | no | dev mean difference -0.1691 is not above 0 |
| 18 | d993ba2c | holdout | +0.3231 | -0.8653 | [-2.37, +0.238] | no | holdout gain -20.3%, 95% CI [-2.37, +0.2383]: below the 2% minimum gain |
| 19 | 9b037c32 | dev | -0.2075 | - | - | no | dev mean difference -0.2075 is not above 0 |
| 20 | 88588083 | holdout | +0.2659 | -0.7722 | [-2.36, +0.664] | no | holdout gain -18.2%, 95% CI [-2.359, +0.6636]: below the 2% minimum gain |
| 21 | e704fece | dev | -0.3901 | - | - | no | dev mean difference -0.3901 is not above 0 |
| 22 | 5b291266 | holdout | +0.3117 | -0.2202 | [-0.74, +0.238] | no | holdout gain -6.5%, 95% CI [-0.74, +0.2382]: below the 2% minimum gain |
| 23 | 32815655 | holdout | +0.1424 | +0.2916 | [+0.0476, +0.568] | yes | accepted: holdout gain +6.7%, 95% CI [+0.04759, +0.5679] |
| 24 | 76d8a45b | holdout | +0.09847 | -0.1633 | [-0.618, +0.247] | no | holdout gain -5.0%, 95% CI [-0.6179, +0.247]: below the 2% minimum gain |
| 25 | 7fb6151a | holdout | +0.167 | +0.1125 | [-0.566, +0.914] | no | holdout gain +2.8%, 95% CI [-0.5662, +0.9143]: interval reaches 0 |
| 26 | 8db74938 | holdout | +0.2684 | -0.4835 | [-1.23, +0.165] | no | holdout gain -14.9%, 95% CI [-1.23, +0.1648]: below the 2% minimum gain |
| 27 | 29d650f5 | dev | -0.3621 | - | - | no | dev mean difference -0.3621 is not above 0 |
| 28 | 602d194e | dev | -0.3307 | - | - | no | dev mean difference -0.3307 is not above 0 |
| 29 | 49e008f2 | holdout | +0.06827 | +0.1142 | [-0.165, +0.39] | no | holdout gain +2.8%, 95% CI [-0.1654, +0.3902]: interval reaches 0 |
| 30 | 8abeacf2 | holdout | +0.3516 | -0.03567 | [-0.675, +0.405] | no | holdout gain -1.1%, 95% CI [-0.675, +0.4051]: below the 2% minimum gain |
| 31 | 8c62f025 | holdout | +0.4361 | -1.04 | [-2.56, +0.254] | no | holdout gain -22.2%, 95% CI [-2.564, +0.2543]: below the 2% minimum gain |
| 32 | d85c6dd5 | dev | -0.2132 | - | - | no | dev mean difference -0.2132 is not above 0 |
| 33 | 884b4e0b | dev | -0.8325 | - | - | no | dev mean difference -0.8325 is not above 0 |
| 34 | 1676c6fa | dev | -0.1247 | - | - | no | dev mean difference -0.1247 is not above 0 |
| 35 | 7ca2306f | dev | -0.0294 | - | - | no | dev mean difference -0.0294 is not above 0 |
| 36 | 1e62253f | holdout | +0.3865 | +0.05308 | [-0.432, +0.508] | no | holdout gain +1.1%, 95% CI [-0.432, +0.508]: below the 2% minimum gain |
| 37 | bf836c50 | dev | -0.5736 | - | - | no | dev mean difference -0.5736 is not above 0 |
| 38 | 2d6d0c78 | dev | -1.002 | - | - | no | dev mean difference -1.002 is not above 0 |
| 39 | 6da73160 | dev | -0.2152 | - | - | no | dev mean difference -0.2152 is not above 0 |
| 40 | e7dd3a4c | dev | -0.5845 | - | - | no | dev mean difference -0.5845 is not above 0 |
