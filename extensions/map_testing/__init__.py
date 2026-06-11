from extensions.map_testing.commands import TestingCommands
from extensions.map_testing.listener import TestingListener
from extensions.map_testing.services.checker import MapChecker
from extensions.map_testing.views.approval import (
    ChannelUploadApproval,
    DebugReport,
    SubmitBuggyApproval,
    SubmitCleanApproval,
    ViewTestingChannelButton,
)
from extensions.map_testing.mapdiff import VisualDiffButton
from extensions.map_testing.views.checklist import ChecklistView
from extensions.map_testing.views.testing_menu import TestingMenu


async def setup(bot):
    MapChecker.enabled = bot.map_checks_enabled
    await bot.add_cog(TestingListener(bot))
    await bot.add_cog(TestingCommands(bot))
    # persistent views
    bot.add_view(TestingMenu(bot))
    bot.add_view(ChecklistView())
    bot.add_view(SubmitCleanApproval(bot))
    bot.add_view(SubmitBuggyApproval(bot))
    bot.add_view(ChannelUploadApproval(bot))
    bot.add_view(DebugReport(bot))
    # These buttons encode per-message/per-channel ids, so they're DynamicItems.
    bot.add_dynamic_items(VisualDiffButton, ViewTestingChannelButton)
