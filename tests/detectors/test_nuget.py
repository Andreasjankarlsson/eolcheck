from pathlib import Path

from eolchecker.detectors import DETECTORS, Context
from eolchecker.detectors.nuget import NugetDetector
from eolchecker.models import Dependency, Unrecognised

from ..fakes import index, product


def run(root: Path, rel: str, idx=None):
    ctx = Context(root, index=idx) if idx is not None else Context(root)
    return NugetDetector().detect(root / rel, ctx)


def project(body: str) -> str:
    return f'<Project Sdk="Microsoft.NET.Sdk">{body}</Project>'


def test_applies_to():
    d = NugetDetector()
    for name in ["A.csproj", "B.fsproj", "C.vbproj", "packages.config"]:
        assert d.applies_to(Path(name))
    assert not d.applies_to(Path("Directory.Packages.props"))


def test_package_reference_attribute_and_element(write_files):
    src = Path("A.csproj")
    root = write_files({"A.csproj": project(
        '<ItemGroup><PackageReference Include="Newtonsoft.Json" Version="13.0.3" />'
        '<PackageReference Include="Serilog"><Version>3.1.1</Version></PackageReference></ItemGroup>')})
    assert run(root, "A.csproj").dependencies == [
        Dependency("nuget:newtonsoft.json", "Newtonsoft.Json", "13.0.3", "13.0.3", src),
        Dependency("nuget:serilog", "Serilog", "3.1.1", "3.1.1", src)]


def test_central_package_management(write_files):
    root = write_files({
        "Directory.Packages.props": '<Project><ItemGroup><PackageVersion Include="Serilog" Version="3.1.1" /></ItemGroup></Project>',
        "src/A.csproj": project('<ItemGroup><PackageReference Include="Serilog" /></ItemGroup>'),
    })
    assert run(root, "src/A.csproj").dependencies == [
        Dependency("nuget:serilog", "Serilog", "3.1.1", "3.1.1", Path("src/A.csproj"))]


def test_version_override_wins(write_files):
    root = write_files({
        "Directory.Packages.props": '<Project><ItemGroup><PackageVersion Include="Serilog" Version="3.1.1" /></ItemGroup></Project>',
        "A.csproj": project('<ItemGroup><PackageReference Include="Serilog" VersionOverride="4.0.0" /></ItemGroup>'),
    })
    [dep] = run(root, "A.csproj").dependencies
    assert dep.version == "4.0.0"


def test_range_uses_lowest_bound(write_files):
    root = write_files({"A.csproj": project(
        '<ItemGroup><PackageReference Include="Serilog" Version="[1.2,2.0)" /></ItemGroup>')})
    [dep] = run(root, "A.csproj").dependencies
    assert (dep.version, dep.display) == ("1.2", "[1.2,2.0)")


def test_property_reference_is_not_resolved(write_files):
    root = write_files({"A.csproj": project(
        '<ItemGroup><PackageReference Include="Serilog" Version="$(SerilogVersion)" /></ItemGroup>')})
    [dep] = run(root, "A.csproj").dependencies
    assert (dep.version, dep.display) == (None, None)


def test_update_is_ignored(write_files):
    root = write_files({"A.csproj": project(
        '<ItemGroup><PackageReference Update="Serilog" Version="3.1.1" /></ItemGroup>')})
    assert run(root, "A.csproj").dependencies == []


def test_packages_config(write_files):
    root = write_files({"packages.config": '<packages><package id="EntityFramework" version="6.4.4" targetFramework="net48" /></packages>'})
    assert run(root, "packages.config").dependencies == [
        Dependency("nuget:entityframework", "EntityFramework", "6.4.4", "6.4.4", Path("packages.config"))]


def test_tracked_without_version_is_a_gap(write_files):
    idx = index(product("efcore", "Entity Framework Core", ["pkg:nuget/Microsoft.EntityFrameworkCore"]))
    root = write_files({"A.csproj": project(
        '<ItemGroup><PackageReference Include="Microsoft.EntityFrameworkCore" /></ItemGroup>')})
    assert run(root, "A.csproj", idx).unrecognised == [
        Unrecognised(Path("A.csproj"), "couldn't read the Entity Framework Core version")]


def test_broken_xml_unrecognised(write_files):
    root = write_files({"A.csproj": "<Project><ItemGroup>"})
    assert run(root, "A.csproj").unrecognised == [Unrecognised(Path("A.csproj"), "couldn't parse A.csproj")]


def test_broken_central_props_is_named(write_files):
    root = write_files({
        "Directory.Packages.props": "<Project><ItemGroup>",
        "A.csproj": project('<ItemGroup><PackageReference Include="Serilog" Version="3.1.1" /></ItemGroup>'),
    })
    result = run(root, "A.csproj")
    assert result.unrecognised == [
        Unrecognised(Path("Directory.Packages.props"), "couldn't parse Directory.Packages.props")]
    assert [d.version for d in result.dependencies] == ["3.1.1"]


def test_registered():
    assert any(isinstance(d, NugetDetector) for d in DETECTORS)
