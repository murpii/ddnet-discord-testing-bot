from extensions.map_testing.enums import UploadState
from extensions.map_testing.models.channel_factory import TestingChannel
from extensions.map_testing.models.submissions import Submission
from utils.conn import ddnet_upload


async def upload_submission(session, submission: Submission, tc: TestingChannel, config):
    map_name = tc.map_name
    buf = await submission.buffer()
    try:
        await ddnet_upload(
            session=session,
            config=config,
            asset_type="map",
            buf=buf,
            filename=map_name
        )
    except RuntimeError:
        await submission.set_upload_state(UploadState.ERROR)
        raise

    await submission.set_upload_state(UploadState.UPLOADED)