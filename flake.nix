{
  description = "Armonía del Ser: Core API (armonia-api) — Python 3.13 + uv devShell";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
      in
      {
        devShells.default = pkgs.mkShell {
          name = "armonia-api-dev-shell";
          packages = with pkgs; [
            python313
            uv
            ruff
            pyright
            sqlite
            tea
          ];
          env = {
            UV_PYTHON_PREFERENCE = "only-system";
            UV_PYTHON = "${pkgs.python313}/bin/python3";
          };
        };
      });
}
