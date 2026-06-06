from extensions.map_testing.commands import TestingCommands
from extensions.map_testing.listener import TestingListener
from extensions.map_testing.views.approval import (
    ChannelUploadApproval,
    DebugReport,
    SubmitBuggyApproval,
    SubmitCleanApproval,
)
from extensions.map_testing.mapdiff import VisualDiffButton
from extensions.map_testing.views.checklist import ChecklistView
from extensions.map_testing.views.testing_menu import TestingMenu


async def setup(bot):
    await bot.add_cog(TestingListener(bot))
    await bot.add_cog(TestingCommands(bot))
    # persistent views
    bot.add_view(TestingMenu(bot))
    bot.add_view(ChecklistView())
    bot.add_view(SubmitCleanApproval(bot))
    bot.add_view(SubmitBuggyApproval(bot))
    bot.add_view(ChannelUploadApproval(bot))
    bot.add_view(DebugReport(bot))
    # The version-diff button encodes per-message ids, so it's a DynamicItem.
    bot.add_dynamic_items(VisualDiffButton)
