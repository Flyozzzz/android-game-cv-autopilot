# Template Assets

Game and common UI templates live under this directory.

Example layout:

```text
assets/templates/
  common/
    play_button/
      template.png
  subway-surfers/
    lane_obstacle/
      train_front.png
```

Template metadata is loaded through `TemplateRegistry` and can point to glob
patterns under this folder.
