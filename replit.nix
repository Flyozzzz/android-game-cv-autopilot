{ pkgs }: {
  deps = [
    pkgs.python311
    pkgs.python311Packages.pip
    pkgs.android-tools
    pkgs.nodejs_20
    pkgs.glibcLocales
  ];
  env = {
    LANG = "en_US.UTF-8";
    PIP_USER = "1";
  };
}
