import os
import sys
from abc import ABCMeta, abstractmethod

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.policy import SMTPUTF8
from botocore.exceptions import ClientError

FUNCTIONS_DIR_PATH = os.path.dirname(os.path.dirname(__file__))
sys.path.append(FUNCTIONS_DIR_PATH)

from conf.env import TERAKOYA_GMAIL_ADDRESS
from conf.util import IS_PROD
from utils.aws import ses_client


class IMail(metaclass=ABCMeta):
    def __init__(self, mail_from: str) -> None:
        self.msg: MIMEMultipart
        self.__mail_from = mail_from

    @abstractmethod
    def send(self, mail_to: str, subject: str, body: str, mail_cc: str = "", img_fpath: str = "") -> None:
        raise NotImplementedError()

    def write_to_mime(self, mail_to: str, subject: str, body: str, mail_cc: str = "", img_fpath: str = ""):
        self.msg = MIMEMultipart()
        html_body = f"""
            <html lang="ja">
                <head>
                    <meta http-equiv="Content-Language" content="ja">
                    <meta charset="UTF-8">
                    <title>{subject}</title>
                </head>
                <body>
                    <br/>
                    {body}
                    <br/>
                </body>
            </html>
        """
        self.msg.attach(MIMEText(html_body, "html", policy=SMTPUTF8))
        self.msg["Subject"] = subject if IS_PROD else f"[Dev] {subject}"
        self.msg["To"] = mail_to
        self.msg["From"] = self.__mail_from
        self.msg["Cc"] = mail_cc

        if (not (os.path.isfile(img_fpath))):
            return
        with open(img_fpath, "rb") as f:
            self.msg.attach(MIMEImage(f.read(), name=os.path.basename(img_fpath)))


GMAIL_ACCOUNT = "" if TERAKOYA_GMAIL_ADDRESS is None else TERAKOYA_GMAIL_ADDRESS


class SesMail(IMail):
    def __init__(self, mail_from: str) -> None:
        super().__init__(mail_from)

    def send(self, mail_to: str, subject: str, body: str, mail_cc: str = "", img_fpath: str = "") -> None:
        self.write_to_mime(mail_to, subject, body, mail_cc, img_fpath)
        try:
            # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ses.html#SES.Client.send_raw_email
            response = ses_client.send_raw_email(
                RawMessage={
                    "Data": self.msg.as_string(),
                },
                Destinations=[],
            )
        except ClientError as e:
            print(str(dict(e.response)))
        else:
            print(f"Email sent! Message ID: {response['MessageId']}")
