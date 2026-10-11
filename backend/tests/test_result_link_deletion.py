"""Deletion order must avoid database-cascade/ORM double deletion."""
import warnings

import pytest
from db import SessionLocal
from models import Engagement, JobResultLink, ReconItem, ScanItem, ScanJob, Service
from sqlalchemy.exc import SAWarning


@pytest.mark.parametrize("loaded", [False, True])
def test_engagement_deletion_removes_observation_links_once(program_id, loaded):
    with SessionLocal() as db:
        job = ScanJob(program_id=program_id, owner_github_id="gh_user1", tool_type="nuclei", target_source="scope")
        recon = ReconItem(program_id=program_id, source="gau", url="https://fixture.test/")
        scan = ScanItem(program_id=program_id, source="nuclei", title="Candidate")
        service = Service(program_id=program_id, owner_github_id="gh_user1", host="fixture.test", port=443)
        db.add_all([job, recon, scan, service])
        db.flush()
        links = [JobResultLink(job_id=job.id, recon_id=recon.id),
                 JobResultLink(job_id=job.id, scan_id=scan.id),
                 JobResultLink(job_id=job.id, service_id=service.id)]
        db.add_all(links)
        db.commit()
        link_ids = [link.id for link in links]
    with SessionLocal() as db:
        engagement = db.get(Engagement, program_id)
        if loaded:
            for job in engagement.scan_jobs:
                assert len(job.result_links) == 3
        with warnings.catch_warnings():
            warnings.simplefilter("error", SAWarning)
            db.delete(engagement)
            db.commit()
        assert db.query(JobResultLink).filter(JobResultLink.id.in_(link_ids)).count() == 0
