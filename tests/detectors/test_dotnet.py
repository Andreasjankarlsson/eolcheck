import json
from pathlib import Path

import pytest

from eolchecker.detectors import DETECTORS, Context
from eolchecker.detectors.dotnet import DotnetDetector, parse_tfm
from eolchecker.models import Finding, Unrecognised


def run(root: Path, rel: str):
    return DotnetDetector().detect(root / rel, Context(root))


def sdk_project(tf_xml: str, extra: str = "") -> str:
    return f'<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>{tf_xml}{extra}</PropertyGroup></Project>'


@pytest.mark.parametrize("tfm,expected", [
    ("net8.0", (".NET", "8.0")),
    ("net8.0-windows", (".NET", "8.0")),
    ("net10.0", (".NET", "10.0")),
    ("netcoreapp3.1", (".NET", "3.1")),
    ("net48", (".NET Framework", "4.8")),
    ("net472", (".NET Framework", "4.7.2")),
    ("v4.7.2", (".NET Framework", "4.7.2")),
    ("netstandard2.0", None),
])
def test_parse_tfm(tfm, expected):
    assert parse_tfm(tfm) == expected


def test_applies_to():
    d = DotnetDetector()
    for name in ["Api.csproj", "Lib.fsproj", "Old.vbproj", "global.json"]:
        assert d.applies_to(Path(name))
    assert not d.applies_to(Path("Directory.Build.props"))


def test_sdk_style_csproj(write_files):
    root = write_files({"api/Api.csproj": sdk_project("<TargetFramework>net8.0</TargetFramework>")})
    assert run(root, "api/Api.csproj").findings == [
        Finding(".NET", "dotnet", "8.0", "net8.0", Path("api/Api.csproj"))]


def test_multi_target(write_files):
    root = write_files({"Lib.csproj": sdk_project("<TargetFrameworks>net8.0;net48;netstandard2.0</TargetFrameworks>")})
    found = [(f.component, f.version, f.display) for f in run(root, "Lib.csproj").findings]
    assert found == [(".NET", "8.0", "net8.0"), (".NET Framework", "4.8", "net48")]


def test_old_style_namespaced(write_files):
    xml = ('<?xml version="1.0" encoding="utf-8"?>'
           '<Project ToolsVersion="15.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">'
           '<PropertyGroup><TargetFrameworkVersion>v4.7.2</TargetFrameworkVersion></PropertyGroup></Project>')
    root = write_files({"Web/Web.csproj": xml})
    assert run(root, "Web/Web.csproj").findings == [
        Finding(".NET Framework", "dotnetfx", "4.7.2", "v4.7.2", Path("Web/Web.csproj"))]


def test_directory_build_props(write_files):
    root = write_files({
        "Directory.Build.props": "<Project><PropertyGroup><TargetFramework>net6.0</TargetFramework></PropertyGroup></Project>",
        "src/A/A.csproj": '<Project Sdk="Microsoft.NET.Sdk"></Project>',
    })
    assert run(root, "src/A/A.csproj").findings == [
        Finding(".NET", "dotnet", "6.0", "net6.0", Path("src/A/A.csproj"))]


def test_nearest_props_wins(write_files):
    root = write_files({
        "Directory.Build.props": "<Project><PropertyGroup><TargetFramework>net6.0</TargetFramework></PropertyGroup></Project>",
        "src/Directory.Build.props": "<Project><PropertyGroup><TargetFramework>net8.0</TargetFramework></PropertyGroup></Project>",
        "src/A/A.csproj": '<Project Sdk="Microsoft.NET.Sdk"></Project>',
    })
    [f] = run(root, "src/A/A.csproj").findings
    assert f.version == "8.0"


def test_property_reference(write_files):
    root = write_files({
        "Directory.Build.props": "<Project><PropertyGroup><AppTfm>net8.0</AppTfm></PropertyGroup></Project>",
        "A.csproj": sdk_project("<TargetFramework>$(AppTfm)</TargetFramework>"),
    })
    [f] = run(root, "A.csproj").findings
    assert (f.version, f.display) == ("8.0", "net8.0")


def test_unresolved_property_gap(write_files):
    root = write_files({"A.csproj": sdk_project("<TargetFramework>$(Nope)</TargetFramework>")})
    assert run(root, "A.csproj").unrecognised == [
        Unrecognised(Path("A.csproj"), "couldn't read the .NET target framework")]


def test_no_target_unrecognised(write_files):
    root = write_files({"A.csproj": '<Project Sdk="Microsoft.NET.Sdk"></Project>'})
    assert run(root, "A.csproj").unrecognised == [
        Unrecognised(Path("A.csproj"), "couldn't read the .NET target framework")]


def test_netstandard_only_silent(write_files):
    root = write_files({"Lib.csproj": sdk_project("<TargetFramework>netstandard2.0</TargetFramework>")})
    result = run(root, "Lib.csproj")
    assert (result.findings, result.unrecognised) == ([], [])


def test_global_json(write_files):
    root = write_files({"global.json": json.dumps({"sdk": {"version": "8.0.100"}})})
    assert run(root, "global.json").findings == [
        Finding(".NET", "dotnet", "8.0.100", "SDK 8.0.100", Path("global.json"))]


def test_global_json_without_sdk_silent(write_files):
    root = write_files({"global.json": json.dumps({"msbuild-sdks": {}})})
    result = run(root, "global.json")
    assert (result.findings, result.unrecognised) == ([], [])


def test_broken_xml_unrecognised(write_files):
    root = write_files({"Api.csproj": "<Project><PropertyGroup>"})
    assert run(root, "Api.csproj").unrecognised == [Unrecognised(Path("Api.csproj"), "couldn't parse Api.csproj")]


def test_bom_csproj(write_files):
    root = write_files({"A.csproj": "﻿" + sdk_project("<TargetFramework>net8.0</TargetFramework>")})
    [f] = run(root, "A.csproj").findings
    assert f.version == "8.0"


def test_registered():
    assert any(isinstance(d, DotnetDetector) for d in DETECTORS)
