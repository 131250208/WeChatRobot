#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import signal
from argparse import ArgumentParser

from base.func_report_reminder import ReportReminder
from robot import Robot, __version__
from wcferry import Wcf
from llm_clients import get_all_models

def main(chat_client: str, reason_client: str, chat_model: str, reason_model: str):
    wcf = Wcf(debug=True)

    def handler(sig, frame):
        wcf.cleanup()  # 退出前清理环境
        exit(0)

    signal.signal(signal.SIGINT, handler)

    robot = Robot(wcf, chat_client, reason_client, chat_model, reason_model)
    robot.logger.info(f"WeChatRobot【{__version__}】成功启动···")

    # 机器人启动发送测试消息
    robot.sendTextMsg("机器人启动成功！", "filehelper")

    # 接收消息
    # robot.enableRecvMsg()     # 可能会丢消息？
    robot.enableReceivingMsg()  # 加队列

    # 每天 7 点发送天气预报
    robot.onEveryTime("07:00", robot.weatherReport)

    # 每天 7:30 发送新闻
    robot.onEveryTime("07:30", robot.newsReport)

    # 每天 16:30 提醒发日报周报月报
    robot.onEveryTime("16:30", ReportReminder.remind, robot=robot)


    # 让机器人一直跑
    robot.keepRunningAndBlockProcess()


if __name__ == "__main__":
    from wechat_bot_config import *  # 直接从当前目录的配置文件导入
    parser = ArgumentParser()
    parser.add_argument('-c', type=str, default=CHAT_CLIENT, help=f'选择模型参数: {get_all_models()}')
    parser.add_argument('-r', type=str, default=REASON_CLIENT, help=f'选择模型参数: {get_all_models()}')
    parser.add_argument('-cm', type=str, default=CHAT_MODEL_NAME, help=f'具体的模型名')
    parser.add_argument('-rm', type=str, default=REASON_MODEL_NAME, help=f'具体的模型名')
    args = [parser.parse_args().c, parser.parse_args().r, parser.parse_args().cm, parser.parse_args().rm]
    main(*args)
