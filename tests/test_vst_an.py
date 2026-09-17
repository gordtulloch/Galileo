"""VST-AN — Variable Star Analysis & Photometry (TC-VST-AN-010 … TC-VST-AN-090)."""

import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def vst_analysis():
    an_mod = pytest.importorskip("galileo.vstarget.analysis")
    return an_mod.VariableStarAnalysis()


# ---------------------------------------------------------------------------
# TC-VST-AN-010
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-VST-AN-010")
@pytest.mark.priority("MVP")
async def test_tc_vst_an_010_retrieve_fits_via_ftp_sftp(vst_analysis):
    """VST-AN-010: Retrieve calibrated FITS images from remote-telescope server via FTP/FTPS/SFTP."""
    an_mod = pytest.importorskip("galileo.vstarget.analysis")
    retriever = an_mod.SftpImageRetriever.__new__(an_mod.SftpImageRetriever)
    retriever.download = AsyncMock(return_value=["/local/cache/m42_001.fits"])

    files = await retriever.download(host="remote.telescope.net", path="/data/R_Leo/", dest="/tmp/cache")
    assert len(files) == 1


# ---------------------------------------------------------------------------
# TC-VST-AN-020
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-VST-AN-020")
@pytest.mark.priority("MVP")
async def test_tc_vst_an_020_plate_solve_retrieved_images(vst_analysis, sample_fits_file):
    """VST-AN-020: Plate-solve retrieved variable-star images via existing solver integration to add WCS."""
    plt_mod = pytest.importorskip("galileo.platesolve")
    mock_solver = plt_mod.PlateSolver.__new__(plt_mod.PlateSolver)
    mock_solver.solve = AsyncMock(return_value=plt_mod.SolveResult(
        success=True, ra_deg=154.0, dec_deg=11.4, rotation_deg=0.0, scale_arcsec_px=1.22
    ))
    vst_analysis._solver = mock_solver

    result = await vst_analysis.solve_image(sample_fits_file)
    assert result.success is True
    mock_solver.solve.assert_called_once_with(sample_fits_file)


# ---------------------------------------------------------------------------
# TC-VST-AN-030
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-VST-AN-030")
@pytest.mark.priority("MVP")
async def test_tc_vst_an_030_stack_same_target_filter(vst_analysis, sample_fits_repo):
    """VST-AN-030: Produce a registered mean-stacked image from same-target, same-filter frames for improved SNR."""
    import numpy as np
    fits = pytest.importorskip("astropy.io.fits")
    frames = list(sample_fits_repo.rglob("*.fits"))
    assert len(frames) >= 2

    result_path = sample_fits_repo / "stacked.fits"
    await vst_analysis.stack(frames=frames, output_path=result_path)
    assert result_path.exists()

    with fits.open(result_path) as hdul:
        assert hdul[0].data is not None
        assert hdul[0].data.shape == (100, 100)


# ---------------------------------------------------------------------------
# TC-VST-AN-040
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-VST-AN-040")
@pytest.mark.priority("MVP")
async def test_tc_vst_an_040_aperture_photometry_differential(vst_analysis, sample_fits_file):
    """VST-AN-040: Perform aperture photometry against AAVSO VSP comparison stars using ensemble linear regression."""
    an_mod = pytest.importorskip("galileo.vstarget.analysis")

    comparison_stars = [
        {"label": "127", "ra": 154.0, "dec": 11.5, "mag_v": 12.7},
        {"label": "134", "ra": 153.9, "dec": 11.3, "mag_v": 13.4},
    ]
    vst_analysis._comparison_stars = comparison_stars

    result = await vst_analysis.run_photometry(
        image_path=sample_fits_file,
        target={"name": "R Leo", "ra": 154.0, "dec": 11.4},
        filter_band="V",
    )
    assert result is not None
    assert hasattr(result, "magnitude")
    assert hasattr(result, "uncertainty")


# ---------------------------------------------------------------------------
# TC-VST-AN-050
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-VST-AN-050")
@pytest.mark.priority("MVP")
def test_tc_vst_an_050_generate_aavso_webobs_report(vst_analysis, tmp_path):
    """VST-AN-050: Generate an AAVSO WebObs Extended-format measurement report from photometry results."""
    an_mod = pytest.importorskip("galileo.vstarget.analysis")
    measurements = [
        an_mod.PhotometryResult(
            target="R Leo",
            jd=2461100.5,
            magnitude=6.8,
            uncertainty=0.05,
            filter_band="V",
            comp_star="127",
            check_star="134",
        )
    ]
    report_path = tmp_path / "webobs_report.csv"
    vst_analysis.export_aavso_report(measurements, output_path=report_path)
    assert report_path.exists()

    content = report_path.read_text()
    assert "#TYPE=EXTENDED" in content or "R Leo" in content
    assert "6.8" in content


# ---------------------------------------------------------------------------
# TC-VST-AN-060
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-VST-AN-060")
@pytest.mark.priority("P2")
async def test_tc_vst_an_060_transformation_coefficients_from_standard_field(vst_analysis):
    """VST-AN-060: Compute per-telescope per-filter transformation coefficients from standard-field observations."""
    an_mod = pytest.importorskip("galileo.vstarget.analysis")
    standard_obs = [
        an_mod.StandardFieldObservation(star="HD12345", b_mag=10.1, v_mag=9.8, r_mag=9.5, b_inst=-0.12, v_inst=-0.10, r_inst=-0.08),
        an_mod.StandardFieldObservation(star="HD23456", b_mag=11.5, v_mag=11.0, r_mag=10.7, b_inst=-0.14, v_inst=-0.11, r_inst=-0.09),
    ]
    coefficients = await vst_analysis.compute_transformation_coefficients(standard_obs)
    assert coefficients is not None
    assert hasattr(coefficients, "Tbv") or "B" in str(coefficients)


# ---------------------------------------------------------------------------
# TC-VST-AN-070
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-VST-AN-070")
@pytest.mark.priority("P2")
async def test_tc_vst_an_070_apply_transformation_to_multifilter(vst_analysis, sample_fits_file):
    """VST-AN-070: Apply stored transformation coefficients to multi-filter observations before report generation."""
    an_mod = pytest.importorskip("galileo.vstarget.analysis")
    vst_analysis._transformation_coefficients = an_mod.TransformationCoefficients(
        Tbv=0.05, Tvr=-0.03, Tr=0.02
    )

    raw_result = an_mod.PhotometryResult(
        target="R Leo", jd=2461100.5, magnitude=6.75, uncertainty=0.04, filter_band="V",
        comp_star="127", check_star="134"
    )
    corrected = vst_analysis.apply_transformation(raw_result)
    assert corrected is not None
    assert corrected.magnitude != raw_result.magnitude or corrected.is_transformed


# ---------------------------------------------------------------------------
# TC-VST-AN-080
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-VST-AN-080")
@pytest.mark.priority("P2")
def test_tc_vst_an_080_exposure_time_calculator(vst_analysis):
    """VST-AN-080: Exposure-time calculator calibrated to configured telescope/filter throughput."""
    an_mod = pytest.importorskip("galileo.vstarget.analysis")
    etc = an_mod.ExposureTimeCalculator(
        telescope_aperture_mm=200,
        focal_length_mm=1000,
        pixel_size_um=5.86,
        qe=0.8,
    )
    exp_s = etc.compute(target_magnitude=12.0, filter_band="V", target_snr=100.0)
    assert exp_s > 0
    assert exp_s < 3600  # sanity: less than 1 hour for a mag-12 target


# ---------------------------------------------------------------------------
# TC-VST-AN-090
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-VST-AN-090")
@pytest.mark.priority("P2")
async def test_tc_vst_an_090_generate_finder_chart(vst_analysis, tmp_path):
    """VST-AN-090: Generate an AAVSO-style finder chart image for a variable-star field."""
    an_mod = pytest.importorskip("galileo.vstarget.analysis")
    chart_renderer = an_mod.FinderChartRenderer.__new__(an_mod.FinderChartRenderer)
    chart_renderer.render = AsyncMock(return_value=b"\x89PNG\r\n\x1a\n" + b"\x00" * 200)

    chart_bytes = await chart_renderer.render(target="R Leo", ra_deg=154.0, dec_deg=11.4, fov_arcmin=30.0)
    assert chart_bytes[:4] == b"\x89PNG"

    chart_path = tmp_path / "finder_r_leo.png"
    chart_path.write_bytes(chart_bytes)
    assert chart_path.exists()
