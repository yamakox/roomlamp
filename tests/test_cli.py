from click.testing import CliRunner

from roomlamp.cli import main


def test_cli_help() -> None:
    result = CliRunner().invoke(main, ['--help'])
    assert result.exit_code == 0
    assert '--kubeconfig' in result.output
    assert '--context' in result.output
