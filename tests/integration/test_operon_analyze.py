import tempfile
import os
import shutil
from operon_analyzer.analyze import analyze, load_analyzed_operons
from operon_analyzer.rules import RuleSet, FilterSet
from operon_analyzer.visualize import build_operon_dictionary, plot_operons
import pytest


def test_reads_file_correctly():
    # there were missing proteins even though they were being used as the seed for a search, meaning
    # we knew they were definitely in an operon. however, they were sometimes not being plotted.
    # this test ensures that every protein in pipeline output is accounted for, even TnsB which was
    # not showing up in the plots
    pipeline_csv = 'tests/integration/integration_data/operon_analyzer/missing-tnsB.csv'
    with open(pipeline_csv) as f:
        operons = build_operon_dictionary(f)
        operon = operons[('NODE_1005_length_10858_cov_9.0000_ID_1723', '/tmp/dna.fasta', 0, 30655)]
        assert 'tnsB' in operon.feature_names
        assert len(operon) == 9


def test_analyze_multipipline(capsys):
    """ Ensures we can concatenate all our result CSVs and parse them together. """
    rs = RuleSet().require('transposase')

    with open('tests/integration/integration_data/operon_analyzer/multipipeline.csv') as f:
        analyze(f, rs)
        captured = capsys.readouterr()
        stdout = captured.out
        assert stdout.startswith("#")
        assert stdout.count("pass") == 6


def test_analyze(capsys):
    """ Just serves to check that `analyze()` produces output """
    rs = RuleSet().require('transposase') \
                  .exclude('cas3') \
                  .at_most_n_bp_from_anything('transposase', 500) \
                  .at_least_n_bp_from_anything('transposase', 1)

    with open('tests/integration/integration_data/operon_analyzer/transposases.csv') as f:
        analyze(f, rs)
        captured = capsys.readouterr()
        stdout = captured.out
        assert stdout.startswith("#")
        assert stdout.count("pass") == 1


def test_analyze_with_overlapping_filter(capsys):
    """ 
    Test that an overlapping lower-quality cas3 is filtered appropriately.
    Implicitly tests that operon_analyzer can accept and correctly process
    pipeline output that contains bitscores.
    """
    fs = FilterSet().pick_overlapping_features_by_bit_score(0.8)
    rs = RuleSet().require('cas11') \
                  .exclude('cas3')

    with open('tests/integration/integration_data/operon_analyzer/overlapping_cas3.csv') as f:
        analyze(f, rs, fs)
        captured = capsys.readouterr()
        stdout = captured.out
        assert stdout.startswith("#")
        assert stdout.count("pass") == 1


@pytest.mark.slow
def test_visualize_passes():
    pass_count = visualize('pass')
    assert pass_count == 2


@pytest.mark.slow
def test_visualize_failures():
    fail_count = visualize('fail')
    assert fail_count == 4


@pytest.mark.slow
def test_visualize_all():
    count = visualize('')
    assert count == 6


@pytest.mark.slow
def test_visualize_none():
    count = visualize('nonexistent-condition')
    assert count == 0


def visualize(condition: str):
    """
    Creates PNGs of the operons matching the given condition. The idea here is that
    there are four failing and two passing operons. We make PNGs of operons whose
    analysis result field starts with the given condition (which is either "pass" or "fail").
    Tests that use this function just determine whether the expected number of PNGs were made,
    not whether they are correct.
    """
    analysis_csv = 'tests/integration/integration_data/operon_analyzer/analysis.csv'
    pipeline_csv = 'tests/integration/integration_data/operon_analyzer/pipeline.csv'

    # We make a temporary directory to store the PNGs
    tempdir = tempfile.mkdtemp()
    try:
        good_operons = []
        with open(pipeline_csv) as f:
            operons = build_operon_dictionary(f)
        with open(analysis_csv) as f:
            for contig, contig_filename, start, end, result in load_analyzed_operons(f):
                if not result[0].startswith(condition):
                    continue
                op = operons.get((contig, contig_filename, start, end))
                if op is None:
                    continue
                good_operons.append(op)
        plot_operons(good_operons, tempdir)
        files = os.listdir(tempdir)
        count = len([f for f in files if f.endswith(".png")])
    except Exception as e:
        raise e
    finally:
        # clean up the directory and any PNGs that were made
        shutil.rmtree(tempdir)
    return count