from flask import *
from sqlalchemy import *
from sqlalchemy.orm import relationship, deferred
from sqlalchemy.ext.associationproxy import association_proxy
from .mix_ins import *
from drama.helpers.base36 import *
from drama.helpers.lazy import lazy
from drama.__main__ import Base
from .votes import CommentVote

class CommentAux(Base):

	__tablename__ = "comments_aux"

	key_id = Column(Integer, primary_key=True)
	id = Column(Integer, ForeignKey("comments.id"))
	body = Column(String(10000))
	body_html = Column(String(20000))
	ban_reason = Column(String(256), default='')


class Comment(Base, Age_times, Scores, Stndrd, Fuzzing):

	__tablename__ = "comments"

	id = Column(Integer, primary_key=True)
	comment_aux = relationship(
		"CommentAux",
		lazy="joined",
		uselist=False,
		innerjoin=True,
		primaryjoin="Comment.id==CommentAux.id")
	author_id = Column(Integer, ForeignKey("users.id"))
	parent_submission = Column(Integer, ForeignKey("submissions.id"))
	# this column is foreignkeyed to comment(id) but we can't do that yet as
	# "comment" class isn't yet defined
	parent_fullname = Column(Integer)
	created_utc = Column(Integer, default=0)
	edited_utc = Column(Integer, default=0)
	is_banned = Column(Boolean, default=False)
	shadowbanned = Column(Boolean, default=False)
	distinguish_level = Column(Integer, default=0)
	deleted_utc = Column(Integer, default=0)
	is_approved = Column(Integer, default=0)
	approved_utc = Column(Integer, default=0)
	creation_ip = Column(String(64), default='')
	level = Column(Integer, default=0)
	parent_comment_id = Column(Integer, ForeignKey("comments.id"))

	over_18 = Column(Boolean, default=False)
	is_bot = Column(Boolean, default=False)
	banaward = Column(String)
	is_pinned = Column(Boolean, default=False)
	sentto=Column(Integer)

	app_id = Column(Integer, ForeignKey("oauth_apps.id"))
	oauth_app=relationship("OauthApp")

	post = relationship("Submission")
	flags = relationship("CommentFlag", backref="comment")
	author = relationship(
		"User",
		lazy="joined",
		innerjoin=True,
		primaryjoin="User.id==Comment.author_id")

	upvotes = Column(Integer, default=1)
	downvotes = Column(Integer, default=0)

	parent_comment = relationship("Comment", remote_side=[id])
	child_comments = relationship("Comment", remote_side=[parent_comment_id])

	#awards = relationship("AwardRelationship", lazy="joined")

	# These are virtual properties handled as postgres functions server-side
	# There is no difference to SQLAlchemy, but they cannot be written to
	score = deferred(Column(Integer, server_default=FetchedValue()))

	def __init__(self, *args, **kwargs):

		if "created_utc" not in kwargs:
			kwargs["created_utc"] = int(time.time())

		kwargs["creation_ip"] = request.remote_addr

		super().__init__(*args, **kwargs)

	def __repr__(self):

		return f"<Comment(id={self.id})>"

	@property
	@lazy
	def fullname(self):
		return f"t3_{self.base36id}"

	@property
	@lazy
	def score_disputed(self):
		return (self.upvotes+1) * (self.downvotes+1)

	def children(self, v):
		return sorted([x for x in self.child_comments if not x.author.shadowbanned or (v and v.id == x.author_id)], key=lambda x: x.score, reverse=True)

	@property
	@lazy
	def parent(self):

		if not self.parent_submission:
			return None

		if self.level == 1:
			return self.post

		else:
			return g.db.query(Comment).get(self.parent_comment_id)

	@property
	def replies(self):

		r = self.__dict__.get("replies", None)
		if r is None:
			r = self.child_comments
		return r

	@replies.setter
	def replies(self, value):
		self.__dict__["replies"] = value

	@property
	def replies2(self):
		return self.__dict__.get("replies2", [])

	@replies2.setter
	def replies2(self, value):
		self.__dict__["replies2"] = value

	@property
	@lazy
	def permalink(self):
		if self.post: return f"{self.post.permalink}/{self.id}/"
		else: return f"/comment/{self.id}/"

	def rendered_comment(self, v=None, render_replies=True,
						 standalone=False, level=1, **kwargs):

		kwargs["post_base36id"] = kwargs.get(
			"post_base36id", self.post.base36id if self.post else None)

		if self.is_banned or self.deleted_utc > 0:
			if v and v.admin_level > 1:
				return render_template("single_comment.html",
									   v=v,
									   c=self,
									   render_replies=render_replies,
									   standalone=standalone,
									   level=level,
									   **kwargs)

			elif self.any_descendants_live:
				return render_template("single_comment_removed.html",
									   c=self,
									   render_replies=render_replies,
									   standalone=standalone,
									   level=level,
									   **kwargs)
			else:
				return ""

		return render_template("single_comment.html",
							   v=v,
							   c=self,
							   render_replies=render_replies,
							   standalone=standalone,
							   level=level,
							   **kwargs)

	@property
	def active_flags(self):
		if self.is_approved:
			return 0
		else:
			return self.flag_count

	@property
	def json_raw(self):
		data= {
			'id': self.base36id,
			'fullname': self.fullname,
			'level': self.level,
			'author_name': self.author.username,
			'body': self.body,
			'body_html': self.body_html,
			'is_archived': self.is_archived,
			'is_bot': self.is_bot,
			'created_utc': self.created_utc,
			'edited_utc': self.edited_utc or 0,
			'is_banned': bool(self.is_banned),
			'deleted_utc': self.deleted_utc,
			'is_nsfw': self.over_18,
			'permalink': self.permalink,
			'post_id': self.post.base36id,
			'score': self.score_fuzzed,
			'upvotes': self.upvotes_fuzzed,
			'downvotes': self.downvotes_fuzzed,
			#'award_count': self.award_count,
			'is_bot': self.is_bot
			}

		if self.ban_reason:
			data["ban_reason"]=self.ban_reason

		return data


	@property
	def json_core(self):
		if self.is_banned:
			data= {'is_banned': True,
					'ban_reason': self.ban_reason,
					'id': self.base36id,
					'post': self.post.base36id,
					'level': self.level,
					'parent': self.parent_fullname
					}
		elif self.deleted_utc > 0:
			data= {'deleted_utc': self.deleted_utc,
					'id': self.base36id,
					'post': self.post.base36id,
					'level': self.level,
					'parent': self.parent_fullname
					}
		else:

			data=self.json_raw

			if self.level>=2:
				data['parent_comment_id']= base36encode(self.parent_comment_id),

		if "replies" in self.__dict__:
			data['replies']=[x.json_core for x in self.replies]

		return data

	@property
	def json(self):
	
		data=self.json_core

		if self.deleted_utc > 0 or self.is_banned:
			return data

		data["author"]=self.author.json_core
		data["post"]=self.post.json_core

		if self.level >= 2:
			data["parent"]=self.parent.json_core


		return data

		
	@property
	def voted(self):

		x = self.__dict__.get("_voted")
		if x is not None:
			return x

		if g.v:
			x = g.db.query(CommentVote).filter_by(
				comment_id=self.id,
				user_id=g.v.id
			).first()

			if x:
				x = x.vote_type
			else:
				x = 0
		else:
			x = 0
		return x

	@property
	def is_blocking(self):
		return self.__dict__.get('_is_blocking', 0)

	@property
	def is_blocked(self):
		return self.__dict__.get('_is_blocked', 0)

	@property
	def body(self):
		if self.comment_aux: return self.comment_aux.body
		else: return ""

	@body.setter
	def body(self, x):
		self.comment_aux.body = x
		g.db.add(self.comment_aux)

	@property
	def body_html(self):
		return self.comment_aux.body_html

	@body_html.setter
	def body_html(self, x):
		self.comment_aux.body_html = x
		g.db.add(self.comment_aux)

	def realbody(self, v):
		body = self.comment_aux.body_html
		if not v or v.slurreplacer: body = body.replace(" nigger"," 🏀").replace(" Nigger"," 🏀").replace(" NIGGER"," 🏀").replace(" pedo"," libertarian").replace(" Pedo"," Libertarian ").replace(" PEDO"," LIBERTARIAN ").replace(" tranny"," 🚄").replace(" Tranny"," 🚄").replace(" TRANNY"," 🚄").replace("  fag","  cute twink").replace("  Fag","  Cute twink").replace("  FAG","  CUTE TWINK").replace(" faggot"," cute twink").replace(" Faggot"," Cute twink").replace(" FAGGOT"," CUTE TWINK").replace(" trump"," DDR").replace(" Trump"," DDR").replace(" TRUMP"," DDR").replace(" biden"," DDD").replace(" Biden"," DDD").replace(" BIDEN"," DDD").replace(" steve akins"," penny verity oaken").replace(" Steve Akins"," Penny Verity Oaken").replace(" STEVE AKINS"," PENNY VERITY OAKEN").replace(" RETARD"," RSLUR").replace(" rapist"," male feminist").replace(" Rapist"," Male feminist").replace(" RAPIST"," MALE FEMINIST").replace(" RETARD"," RSLUR").replace(" rapist"," male feminist").replace(" Rapist"," Male feminist").replace(" RAPIST"," MALE FEMINIST").replace(" RETARD"," RSLUR").replace(" rapist"," male feminist").replace(" Rapist"," Male feminist").replace(" RAPIST"," MALE FEMINIST").replace(" kill yourself"," keep yourself safe").replace(" KILL YOURSELF"," KEEP YOURSELF SAFE")
		if v and not v.oldreddit: body = body.replace("old.reddit.com", "reddit.com")
		return body

	@property
	def ban_reason(self):
		return self.comment_aux.ban_reason

	@ban_reason.setter
	def ban_reason(self, x):
		self.comment_aux.ban_reason = x
		g.db.add(self.comment_aux)

	@property
	def flag_count(self):
		return len(self.flags)

	#@property
	#def award_count(self):
		#return len(self.awards)

	def collapse_for_user(self, v):

		if self.over_18 and not (v and v.over_18) and not self.post.over_18:
			return True

		if not v:
			return False
			
		if any([x in self.body for x in v.filter_words]):
			return True
		
		if self.is_banned: return True
		
		return False

	@property
	def flagged_by(self):
		return [x.user for x in self.flags]

	@property
	def self_download_json(self):

		#This property should never be served to anyone but author and admin
		if not self.is_banned and not self.is_banned:
			return self.json_core

		data= {
			"author": self.author.name,
			"body": self.body,
			"body_html": self.body_html,
			"is_banned": bool(self.is_banned),
			"deleted_utc": self.deleted_utc,
			'created_utc': self.created_utc,
			'id': self.base36id,
			'fullname': self.fullname,
			'permalink': self.permalink,
			'post_id': self.post.base36id,
			'level': self.level
		}
		if self.level>=2:
			data['parent_comment_id']= base36encode(self.parent_comment_id)

		return data

	@property
	def json_admin(self):
		data= self.json_raw
	
		return data

	@property
	@lazy
	def is_op(self):
		return self.author_id==self.post.author_id
	
	


class Notification(Base):

	__tablename__ = "notifications"

	id = Column(Integer, primary_key=True)
	user_id = Column(Integer, ForeignKey("users.id"))
	comment_id = Column(Integer, ForeignKey("comments.id"))
	read = Column(Boolean, default=False)
	followsender = Column(Integer)
	unfollowsender = Column(Integer)
	blocksender = Column(Integer)
	unblocksender = Column(Integer)

	comment = relationship("Comment", lazy="joined", innerjoin=True)
	user=relationship("User", innerjoin=True)

	# Server side computed values (copied from corresponding comment)
	created_utc = Column(Integer, server_default=FetchedValue())

	def __repr__(self):

		return f"<Notification(id={self.id})>"

	@property
	def voted(self):
		return 0