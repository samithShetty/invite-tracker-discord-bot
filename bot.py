import discord
from discord.ext import commands
import DiscordUtils
import pandas as pd
from typing import Optional
import os


intents = discord.Intents(messages = True, guilds = True, reactions = True, members = True, presences = False)
bot = commands.Bot(command_prefix = "-", intents = intents)
tracker = DiscordUtils.InviteTracker(bot)

count_df = pd.read_csv('csv/invite_count.csv', index_col='User_ID')
inviters_df = pd.read_csv('csv/member_invite_record.csv', index_col = 'Member')
leavers_df = pd.read_csv('csv/member_leaver_record.csv', index_col = 'Leaver')
role_df = pd.read_csv('csv/roles.csv', index_col='Role_ID')


@bot.event
async def on_ready():
    global server, channel
    await tracker.cache_invites()
    print("Bot is online")


#Command to display invate count values
@bot.command(aliases=['invites', 'invite', 'count'])
async def invite_count(ctx, member: Optional[discord.Member] = None):
    if not member: #Set optional parameter so that command can be called on self or by mentioning another user
        member = ctx.author
    
    embed = discord.Embed(
        color = member.color
    )
    embed.set_author(name=member.display_name, icon_url=member.avatar_url)
    try:
        counts = count_df.loc[member.id]
    except KeyError:
        embed.description = 'You currently have **0** valid invites, **0** leavers, and **0** fake/new account invites'
    else:
        embed.description = 'You currently have **{0.Real}** valid invites, **{0.Left}** leavers, and **{0.Fake}** fake/new account invites'.format(counts)
    
    await ctx.send(embed=embed)


@bot.command(aliases = ['setinvites','setcount','set'])
@commands.has_permissions(administrator=True)
async def set_invites(ctx, member: discord.Member, real:int, left:int, fake:int):
    global count_df
    try: #Check to see if the user had an invite count saved already
        count_df.loc[member.id]
    except KeyError: #If not, make a new entry for the member
        new_entry = pd.DataFrame([[real,left,fake]],index=[member.id], columns=count_df.columns)
        count_df = count_df.append(new_entry)
    else: #If yes, then add to it
        count_df.loc[member.id, 'Real'] = real
        count_df.loc[member.id, 'Left'] = left
        count_df.loc[member.id, 'Fake'] = fake
    count_df.to_csv('csv/invite_count.csv', index_label='User_ID')

    await give_roles(member)
    await remove_roles(member)
    await ctx.send(f'New invite count values set for {member.mention}')


# Helper functions for roles, add/remove invite-roles based on current invite count
async def give_roles(member):
    unlocked_roles = role_df[role_df["Invite_Count"] <= count_df.loc[member.id,"Real"]]
    if not isinstance(unlocked_roles,pd.DataFrame): unlocked_roles = pd.DataFrame([unlocked_roles]) #cast to DF if it isnt already
    for role_entry in unlocked_roles.itertuples():
        await member.add_roles(member.guild.get_role(role_entry.Index))

async def remove_roles(member):
    unlocked_roles = role_df[role_df["Invite_Count"] > count_df.loc[member.id,"Real"]]
    if not isinstance(unlocked_roles,pd.DataFrame): unlocked_roles = pd.DataFrame([unlocked_roles]) #cast to DF if it isnt already
    for role_entry in unlocked_roles.itertuples():
        await member.remove_roles(member.guild.get_role(role_entry.Index))


#Command to add a new role with invite requirement and name (can be customized after creation)
@bot.command()
@commands.has_permissions(administrator=True)
async def addrole(ctx, count, *name):
    global role_df
    new_role = await ctx.guild.create_role(name=" ".join(name))
    new_entry = pd.DataFrame([[count]],index=[new_role.id], columns=role_df.columns)
    role_df = role_df.append(new_entry)
    role_df.to_csv('csv/roles.csv', index_label='Role_ID')
    await ctx.send(f'{new_role.mention} has been created with a invite requirement of {count}!')


#Event to remove roles from csv when they are deleted
@bot.event
async def on_guild_role_delete(role):
    #This is called whenever any role is deleted, so we first need to make sure the role is one of ours
    try:
        role_df.loc[role.id]
    except KeyError:
        pass
    else:
        role_df.drop(labels=role.id, inplace=True)
        role_df.to_csv('csv/roles.csv', index_label='Role_ID')
    await role.guild.system_channel.send(f'{role.name} has been deleted and will no longer be automatically assigned')


#When a member joins, check who invited them and update that member's invite count/record 
@bot.event
async def on_member_join(member):
    global count_df
    global inviters_df
    global leavers_df

    inv_user = await tracker.fetch_inviter(member)
    inviter = member.guild.get_member(inv_user.id)
    
    #Update invite counts
    try: #Check to see if the user had an invite count saved already
        count_df.loc[inviter.id]
    except KeyError: #If not, make a new entry for the member
        new_entry = pd.DataFrame([[1,0,0]], index=[inviter.id], columns=count_df.columns)
        count_df = count_df.append(new_entry)
    else: #If yes, then add to it
        count_df.loc[inviter.id,"Real"] += 1
    

    #Update inviter/leaver record
    inviters_df = inviters_df.append(pd.DataFrame([[inviter.id]], index=[member.id], columns=inviters_df.columns))
    inviters_df.to_csv('csv/member_invite_record.csv', index_label='Member')

    try:
        entries =leavers_df.loc[member.id]
    except KeyError:
        return #Member has not left the guild before, no need to update anything
    else:
        for entry in pd.DataFrame([entries]).itertuples():
            if entry.Inviter == inviter.id:
                count_df.loc[inviter.id,"Left"] -= 1
        count_df.to_csv('csv/invite_count.csv', index_label='User_ID')
        leavers_df.drop(labels=member.id, inplace=True)
        leavers_df.to_csv('csv/member_leaver_record.csv', index_label='Leaver')
    
    await give_roles(inviter)
    await member.guild.system_channel.send(f'{inviter.mention} invited {member.mention} to the server!')


#When a member leaves, find who invited them and update their record
@bot.event
async def on_member_remove(member):
    global count_df
    global inviters_df
    global leavers_df

    try:
        inviter = inviters_df.loc[member.id, "Inviter"]
    except KeyError:
        return #Member did not have documented inviter, no adjustment needed
    else:
        #Update count and inviter/leaver records
        count_df.loc[inviter,"Real"] -= 1
        count_df.loc[inviter,"Left"] += 1
        inviters_df.drop(labels=member.id, inplace=True)
        leavers_df = leavers_df.append(pd.DataFrame([[inviter]], index=[member.id], columns=leavers_df.columns))
        
        count_df.to_csv('csv/invite_count.csv', index_label='User_ID')
        inviters_df.to_csv('csv/member_invite_record.csv', index_label='Member')
        leavers_df.to_csv('csv/member_leaver_record.csv', index_label='Leaver')

        await remove_roles(member.guild.get_member(inviter)) #Update roles of inviter 

##Invite Tracker Setup
@bot.event
async def on_invite_create(invite):
    await tracker.update_invite_cache(invite)

@bot.event
async def on_guild_join(guild):
    await tracker.update_guild_cache(guild)

@bot.event
async def on_invite_delete(invite):
    await tracker.remove_invite_cache(invite)

@bot.event
async def on_guild_remove(guild):
    await tracker.remove_guild_cache(guild)


bot.run(os.environ['DISCORD_TOKEN'])